"""Ordinary personnel search: executable filters, parallel recall, stable snapshots.

Search relevance is not a certified factual verdict. Unsupported facts remain
visible as unresolved conditions; no generated model verdict controls each row.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import re
from app.core.config import settings
from app.services.agent_trace import trace_note, trace_stage
from app.services.talent_search import execute_plan, number_value, normalized
from app.services.talent_hybrid import bm25, RESEARCH_FIELDS
from app.services.talent_results import save_result, result_page
from app.services.talent_search_index import ready_index, person_scores
from app.services.embeddings import EmbeddingClient, EmbeddingConfig


def region_value(fields):
    text=str(fields.get('所在国家／城市','')).strip()
    # A source-provided current region, never inferred from education or a name.
    return re.split(r'[/／,，;；\n]',text,maxsplit=1)[0].strip()


def test_predicate(fields, predicate):
    values=[region_value(fields) if f=='@current_region' else str(fields.get(f,'')).strip() for f in predicate.fields]
    values=[v for v in values if v and v.strip().casefold() not in {'—','-','n/a','unknown','未知','不详','未提供'}]
    if not values:
        return None
    if predicate.op in {'gte','lte'}:
        target=number_value(predicate.values[0])
        numbers=[number_value(v) for v in values]
        numbers=[n for n in numbers if n is not None]
        if not numbers:return None
        return any(n>=target if predicate.op=='gte' else n<=target for n in numbers)
    expected=[normalized(v) for v in predicate.values]
    observed=[normalized(v) for v in values]
    if predicate.op=='equals_any':
        # 国家／城市 is a compound source field; country-only values target its
        # explicit first component, never a country inferred from biography.
        if '所在国家／城市' in predicate.fields:
            observed.append(normalized(region_value(fields)))
        return any(v==e for v in observed for e in expected)
    return any(e in v for v in observed for e in expected)


def validate_compiled(plan, sheets):
    headers={f for s in sheets for f in s.headers}
    conditions=list(dict.fromkeys(plan.evidence_conditions))
    compiled={}
    for predicate in (plan.search.predicates if plan.search else []):
        if predicate.condition not in conditions or predicate.condition in compiled:
            raise ValueError('Invalid or duplicate compiled search condition')
        if predicate.kind!='unresolved':
            if not predicate.values or any(not v.strip() for v in predicate.values):
                raise ValueError('Empty search predicate')
            if not predicate.fields or any(f not in headers|{'@current_region'} for f in predicate.fields):
                raise ValueError('Unknown search predicate field')
            if predicate.op in {'gte','lte'} and (len(predicate.values)!=1 or number_value(predicate.values[0]) is None):
                raise ValueError('Invalid numeric search predicate')
        compiled[predicate.condition]=predicate
    return compiled


def search_talents(question, plan, sheets, failures, planner, scope, offset, page_size):
    compiled=validate_compiled(plan,sheets)
    conditions=list(dict.fromkeys(plan.evidence_conditions))
    unresolved=[c for c in conditions if c not in compiled or compiled[c].kind=='unresolved']
    metadata=[p for p in compiled.values() if p.kind=='metadata']
    topics=[p for p in compiled.values() if p.kind=='topic']
    # Older plans still have topic recall expressions; never treat missing fact
    # compilation as proof that a condition is met.
    if not topics and plan.concepts:
        from app.services.talent_search_schema import SearchPredicate
        topics=[SearchPredicate(condition=plan.topic_condition or question,kind='topic',
            fields=list(dict.fromkeys(f for c in plan.concepts for f in c.fields)),
            values=list(dict.fromkeys(t for c in plan.concepts for t in c.terms))[:80])]
    broad=plan.model_copy(update={'concepts':[]})
    groups=execute_plan(broad,sheets,all_records=True,include_unranked=True)
    originals={(s.source_id,s.sheet,r['row']):r for s in sheets for r in s.rows}
    entries=[]; unknown=0; rejected=0
    for group in groups:
        for row in group.get('records',[]):
            original=originals[(group['source_id'],group['sheet'],row['excel_row'])]
            row['fields']=dict(original['fields'])
            checks=[test_predicate(row['fields'],p) for p in metadata]
            if False in checks:
                rejected+=1;continue
            if None in checks:
                unknown+=1;continue
            entries.append((group,row,original.get('talent_id')))
    corpus_count=sum(len(s.rows) for s in sheets)
    documents=['\n'.join(str(v) for f,v in row['fields'].items() if f in RESEARCH_FIELDS or any(f in p.fields for p in topics)) for _,row,_ in entries]
    topic_query=' '.join(p.condition for p in topics)
    # Embeddings describe the scientific topics, not the conversational command,
    # geographic filters or metric sort. This also preserves follow-up topics.
    embedding_query=' '.join(dict.fromkeys(v for p in topics for v in p.values))
    dense={}; vector_status='not_needed'; covered=0
    index=None
    if topics and entries:
        index,vector_status=ready_index(getattr(planner,'search_db',None),sheets,scope)
    def lexical():
        texts=[normalized(text) for text in documents]
        per_topic=[bm25(' '.join(p.values+p.related_values), documents) for p in topics]
        supports=[[any(normalized(v) in text for v in p.values) for text in texts] for p in topics]
        # Related terms expand recall; only direct terms admit a result. A
        # positive Chinese bigram score alone proves neither kind of match.
        for predicate,scores in zip(topics,per_topic):
            for i,text in enumerate(texts):
                if not any(normalized(v) in text for v in predicate.values+predicate.related_values):scores[i]=0
        return ([sum(scores[i] for scores in per_topic) for i in range(len(entries))],
                [all(s[i] for s in supports) for i in range(len(entries))])
    if topics and entries:
        with trace_stage('并行文本与向量召回'):
            with ThreadPoolExecutor(max_workers=1,thread_name_prefix='talent-bm25') as pool:
                future=pool.submit(lexical)
                if index is not None and index[0]:
                    allowed={person for _,_,person in entries if person}
                    covered=len(set(index[0])&allowed)
                    try:
                        client=EmbeddingClient(EmbeddingConfig(settings.embedding_api_url,settings.embedding_api_key,
                            settings.embedding_model,settings.talent_search_embedding_timeout),
                            db=getattr(planner,'search_db',None),knowledge_base_id=getattr(planner,'search_base',None))
                        vector=client.embed_text(embedding_query)
                        dense=person_scores(index,vector,allowed)
                        vector_status='ready'
                    except Exception as exc:
                        vector_status='unavailable'
                        trace_note('快速搜索向量降级',status='fallback',error_type=type(exc).__name__)
                lexical_scores,supported=future.result()
    else:
        lexical_scores=[0]*len(entries)
        supported=[True]*len(entries)
    limit=settings.talent_search_candidates
    lex_order=sorted((i for i,s in enumerate(lexical_scores) if s>0),key=lambda i:lexical_scores[i],reverse=True)[:limit]
    # Reserve a full direct-evidence channel independently of broad recall.
    direct_order=sorted((i for i,ok in enumerate(supported) if ok),key=lambda i:lexical_scores[i],reverse=True)[:limit] if topics else []
    dense_order=sorted((i for i,e in enumerate(entries) if e[2] in dense),key=lambda i:dense[entries[i][2]],reverse=True)[:limit]
    fused={}
    for order,weight in ((lex_order,settings.knowledge_hybrid_lexical_weight),(dense_order,settings.knowledge_hybrid_embedding_weight)):
        for rank,i in enumerate(order,1):fused[i]=fused.get(i,0)+weight/(60+rank)
    for rank,i in enumerate(direct_order,1):
        if i not in lex_order:fused[i]=fused.get(i,0)+settings.knowledge_hybrid_lexical_weight/(60+rank)
    # Recall rank is not evidence of topic membership. In the absence of a
    # calibrated semantic acceptance model, require direct topic/alias support
    # in the original business fields. RRF/rerank may order admitted records,
    # but must never promote unsupported neighbours into the result count.
    # Apply before top-k: unrelated dense neighbours must not evict lexical hits.
    unsupported=sum(not supported[i] for i in fused) if topics else 0
    selected=(sorted((i for i in fused if supported[i]),key=lambda i:fused[i],reverse=True)[:limit]
              if topics else list(range(len(entries))))
    rerank_status='not_needed'
    if topics:
        from app.services.talent_rerank import rerank
        with trace_stage('候选相关性重排'):
            reordered,rerank_status=rerank(topic_query,[documents[i] for i in selected],
                getattr(planner,'search_db',None),getattr(planner,'search_base',None))
        selected=[selected[i] for i in reordered]
    if plan.sort_by:
        def metric(i):
            value=number_value(entries[i][1]['fields'].get(plan.sort_by,''))
            return value is None,(-value if plan.descending else value) if value is not None else 0
        selected.sort(key=metric)
    if plan.result_limit is not None:selected=selected[:plan.result_limit]
    for group in groups:
        group['records']=[];group['matched_records']=0
    order=[];rankable=0
    for rank,i in enumerate(selected):
        group,row,_=entries[i]
        snippets=[]
        for p in topics:
            for field in dict.fromkeys(p.fields+sorted(RESEARCH_FIELDS)):
                text=str(row['fields'].get(field,''))
                term=next((v for v in p.values if normalized(v) in normalized(text)),None)
                if term:
                    at=text.casefold().find(term.casefold());at=max(0,at-50)
                    snippets.append(field+'：'+text[at:at+220])
                    break
        row['fields']['检索依据']='；'.join(snippets)[:600] or ('语义相似召回，请结合原始资料判断' if topics else '结构化字段筛选')
        row['_search_order']=rank
        group['records'].append(row);group['matched_records']+=1
        order.append([group['source_id'],group['sheet'],row['excel_row']])
        if plan.sort_by and number_value(row['fields'].get(plan.sort_by,'')) is not None:rankable+=1
    retrieval={'mode':'BM25 + dense + RRF' if dense else 'BM25','vector_status':vector_status,
        'dense_covered_people':covered,'eligible_people':len(entries),'lexical_candidates':len(lex_order),
        'dense_candidates':len(dense_order),'candidate_limit':limit,'rerank':rerank_status,
        'admission':'direct_topic_evidence' if topics else 'structured_fields',
        'direct_candidates':len(direct_order),
        'unsupported_candidates':unsupported}
    evidence={'search_mode':'hybrid','results':groups,'plan':plan.model_dump(),'matched':len(selected),
        'result_order':order,'rankable':rankable if plan.sort_by else None,
        'missing':len(selected)-rankable if plan.sort_by else None,'unranked':bool(plan.sort_by and selected and not rankable),
        'ranking_scope':'matched_results' if plan.sort_by else None,'verification':None,'retrieval':retrieval,
        'unreadable_files':failures,'unresolved_conditions':unresolved,'can_continue':False,
        'coverage':{'eligible':corpus_count,'evaluated':0,'pending':0,'unknown':unknown,'adjacent':0,
            'complete':not topics and not unresolved and not failures and not unknown,
            'ranking_proven':False,'result_limit_reached':plan.result_limit is not None and len(selected)>=plan.result_limit},
        'status':'search_results'}
    evidence['snapshot_id']=save_result(scope,question,evidence['plan'],evidence)
    trace_note('普通人才搜索完成',returned=len(selected),unresolved_conditions=unresolved,metadata_unknown=unknown,**retrieval)
    return result_page(deepcopy(evidence),offset,page_size)
