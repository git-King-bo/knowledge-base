"""Talent-level BM25 + dense retrieval, joined through persisted chunk ownership."""
import json
import math
import re
from pathlib import Path
from collections import Counter
from sqlalchemy import select
from sqlalchemy.orm import load_only
from app.core.config import settings
from app.core.security import usage_counter
from app.core.limits import MAX_MODEL_CALLS_PER_OPERATION
from app.db.models import ChunkTalentModel, KnowledgeChunkModel, KnowledgeChunkEmbeddingModel, SourceIndexModel
from app.services.embeddings import EmbeddingClient
from app.services.agent_trace import trace_note, trace_stage
from app.services.retrieval_cache import dense_scores
from app.services.talent_search import execute_plan, normalized

RESEARCH_FIELDS = {'姓名','英文名','当前机构','当前职务','详细个人简介','代表成果','研究方向',
                   '细分关键词','领域','未来产业方向','工作经历','创业／项目经历','技术角色定位'}


def tokens(text):
    result = re.findall(r'[a-z0-9]+', text.lower())
    for run in re.findall(r'[\u4e00-\u9fff]+', text):
        result.extend(run[i:i+2] for i in range(len(run)-1))
    return result


def bm25(query, documents):
    vectors = [Counter(tokens(text)) for text in documents]
    lengths = [sum(v.values()) for v in vectors]
    average = sum(lengths) / max(len(lengths), 1) or 1
    terms = set(tokens(query))
    df = {term: sum(term in vector for vector in vectors) for term in terms}
    scores = []
    for vector, length in zip(vectors, lengths):
        score = 0.0
        for term in terms:
            frequency = vector.get(term, 0)
            if frequency:
                idf = math.log(1 + (len(vectors)-df[term]+0.5)/(df[term]+0.5))
                score += idf * frequency * 2.2 / (frequency + 1.2*(0.25+0.75*length/average))
        scores.append(score)
    return scores


def hybrid_talents(db, knowledge_base_id, question, plan, sheets):
    # Apply explicit structured constraints, but do not require a keyword hit for dense candidates.
    broad = plan.model_copy(update={'concepts': []})
    all_results = execute_plan(broad, sheets, all_records=True, include_unranked=True) if plan.filters else []
    if plan.filters:
        originals={(s.source_id,s.sheet,r['row']):r['fields'] for s in sheets for r in s.rows}
        for group in all_results:
            for record in group.get('records',[]):
                record['fields']=dict(originals[(group['source_id'],group['sheet'],record['excel_row'])])
    else:
        # Full rows retain education/work evidence even when research snippets alone were retrieved.
        for sheet in sheets:
            all_results.append({'source_id':sheet.source_id,'file':sheet.filename,'sheet':sheet.sheet,
                'scanned_records':len(sheet.rows),'matched_records':len(sheet.rows),
                'records':[{'excel_row':r['row'],'fields':dict(r['fields'])} for r in sheet.rows]})
    ids = {(s.source_id,s.sheet,r['row']):r.get('talent_id') for s in sheets for r in s.rows}
    entries = [(group,record) for group in all_results for record in group.get('records',[])]
    recall_fields=RESEARCH_FIELDS | {field for group in plan.concepts for field in group.fields}
    documents = ['\n'.join(str(v) for k,v in record['fields'].items() if k in recall_fields)
                 for _,record in entries]
    # Research query excludes university/geography restrictions; those are checked against whole rows.
    query = ' '.join(group.terms[0] for group in plan.concepts)
    expanded_query = ' '.join(term for group in plan.concepts for term in group.terms)
    lexical = bm25(expanded_query,documents)
    direct_terms = {normalized(term) for group in plan.concepts for term in group.terms
                    if normalized(term) in normalized(question)}
    exact = [sum(normalized(term) in normalized(text) for term in direct_terms) for text in documents]
    for i, score in enumerate(exact):
        lexical[i] += score * 8
    lexical_order = sorted((i for i,v in enumerate(lexical) if v>0),key=lambda i:lexical[i],reverse=True)[:60]
    id_to_index = {ids.get((g['source_id'],g['sheet'],r['excel_row'])):i for i,(g,r) in enumerate(entries)}
    id_to_index.pop(None,None)
    dense_order = []
    dense_count = 0
    mode = 'BM25 + dense + RRF'
    client = EmbeddingClient(db=db, knowledge_base_id=knowledge_base_id)
    try:
        if not client.enabled:
            raise RuntimeError('embedding disabled')
        query_vector = client.embed_text(query)
        stale = select(SourceIndexModel.source_id).where(SourceIndexModel.edited.is_(True),SourceIndexModel.revision != SourceIndexModel.indexed_revision)
        statement = select(KnowledgeChunkModel,KnowledgeChunkEmbeddingModel,ChunkTalentModel.talent_id).options(
            load_only(KnowledgeChunkModel.id),
            load_only(KnowledgeChunkEmbeddingModel.chunk_id,KnowledgeChunkEmbeddingModel.embedding_model,
                      KnowledgeChunkEmbeddingModel.embedding_dim,KnowledgeChunkEmbeddingModel.created_at))\
            .join(KnowledgeChunkEmbeddingModel,KnowledgeChunkEmbeddingModel.chunk_id==KnowledgeChunkModel.id)
        statement = statement.join(ChunkTalentModel,ChunkTalentModel.chunk_id==KnowledgeChunkModel.id).where(
            ChunkTalentModel.talent_id.in_(list(id_to_index)),~KnowledgeChunkModel.source_id.in_(stale),
            KnowledgeChunkEmbeddingModel.embedding_model==settings.embedding_model,
            KnowledgeChunkEmbeddingModel.embedding_dim==len(query_vector)).order_by(KnowledgeChunkModel.id)
        with trace_stage('读取人才向量索引元数据'):
            rows = db.execute(statement).all()
        def load_vectors():
            with trace_stage('加载人才向量正文（缓存未命中）'):
                chunk_ids=[chunk.id for chunk,_,_ in rows]
                return dict(db.execute(select(KnowledgeChunkEmbeddingModel.chunk_id,KnowledgeChunkEmbeddingModel.embedding_json)
                    .where(KnowledgeChunkEmbeddingModel.chunk_id.in_(chunk_ids))).all()) if chunk_ids else {}
        with trace_stage('人才向量缓存与相似度计算'):
            scores = dense_scores([(c,e) for c,e,_ in rows],query_vector,settings.embedding_model,str(db.get_bind().url),load_vectors=load_vectors,
                cache_dir=Path(settings.upload_dir).parent / 'cache' / 'talent-vectors')
        by_person = {}
        for chunk,_,talent_id in rows:
            score = scores.get(chunk.id)
            if score is not None and score > 0:
                i = id_to_index[talent_id]
                by_person[i] = max(score,by_person.get(i,0))
        dense_count = len(by_person)
        dense_order = sorted(by_person,key=by_person.get,reverse=True)[:60]
        if not dense_count:
            raise RuntimeError('no compatible talent embeddings')
    except Exception as exc:
        trace_note('人才向量检索降级',status='fallback',reason=str(exc)[:500])
        mode = 'BM25（向量检索不可用，已降级）'
    fused = {}
    for order in (lexical_order,dense_order):
        for rank,i in enumerate(order,1):
            fused[i] = fused.get(i,0) + 1/(60+rank)
    ordered = sorted(fused,key=lambda i:(fused[i],exact[i]),reverse=True)
    # Stay inside the existing per-request model budget. Report candidate truncation explicitly.
    slots = max(0,MAX_MODEL_CALLS_PER_OPERATION-(usage_counter.get() or {}).get('dispatched',0))
    selected = ordered[:slots*6]
    selected_rank = {i:rank for rank,i in enumerate(selected)}
    for group in all_results:
        group['records'] = []
        group['matched_records'] = 0
    for i in selected:
        group,record = entries[i]
        record['_hybrid_rank'] = selected_rank[i]
        group['records'].append(record)
        group['matched_records'] += 1
    metadata = {'mode':mode,'lexical_candidates':len(lexical_order),'dense_candidates':dense_count,
        'candidate_pool':len(ordered),'verified_pool':len(selected),'limited':len(ordered)>len(selected),
        'query':query}
    trace_note('人才混合召回',**metadata)
    return all_results,metadata
