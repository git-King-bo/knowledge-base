"""End-to-end contracts for field indexes, evidence admission and atomic publication."""
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch,Mock
import numpy as np
from openpyxl import Workbook
from sqlalchemy import select,delete

import test_workspace as workspace
import test_production as production
from app.core.config import settings
from app.db.models import TalentModel,KnowledgeChunkModel,KnowledgeChunkEmbeddingModel,SourceIndexModel,ImportJobModel
from app.services.import_jobs import process_job,enqueue,fingerprint
from app.services.talent_documents import field_chunks
from app.services.talent_search import TalentPlan,TalentSheet,talent_context
from app.services.talent_search_schema import SearchSpec,SearchPredicate
from app.services.talent_fast_search import search_talents,test_predicate as predicate_match
from app.services.talent_structured_router import compile_structured
from app.services.talent_results import load_result
from app.services.embeddings import EmbeddingClient,EmbeddingConfig
from app.schemas.usage import TokenUsage,ChatResult
from app.ai.providers.openai_compatible import OpenAICompatibleProvider


class DocumentContracts(unittest.TestCase):
    def test_fields_are_complete_owned_bounded_and_exclude_contacts(self):
        text='实验控制与科学建模。'*150
        drafts=field_chunks({'姓名':'A','当前机构':'Institute A','详细个人简介':text,
            '领域':'AI4S','公开联系方式线索':'secret@example.invalid','操作记录':'private note'},max_chars=480,overlap=80)
        self.assertGreater(len(drafts),2)
        for draft in drafts:
            self.assertLessEqual(len(draft['content']),480)
            self.assertIn('姓名：A',draft['content'])
            self.assertIn('字段：',draft['content'])
            self.assertNotIn('secret@example.invalid',draft['content'])
            self.assertNotIn('private note',draft['content'])
        self.assertIn('领域：AI4S','\n'.join(d['content'].replace('字段：领域\n','领域：') for d in drafts))

    def test_registry_aliases_match_authorized_fields_without_substring_acronym_errors(self):
        p=SearchPredicate(condition='institution',kind='metadata',slot='current_institution',fields=['当前机构'],values=['中国科学院'])
        for text in ['中科院自动化所','中国科学院自动化研究所','Institute, Chinese Academy of Sciences','CAS']:
            self.assertTrue(predicate_match({'当前机构':text},p),text)
        self.assertFalse(predicate_match({'当前机构':'Case Western Reserve University'},p))
        self.assertFalse(predicate_match({'当前机构':'中国社会科学院'},p))
        self.assertFalse(predicate_match({'当前机构':'Other','教育经历':'中国科学院'},p))

    def test_composite_queries_never_become_one_local_topic(self):
        sheet=TalentSheet('s','f','people',['姓名','领域','当前机构'],[
            {'row':2,'fields':{'姓名':'A','领域':'AI4S','当前机构':'中科院自动化所'}}])
        for question in ['查找中科院从事AI4s领域的人才','查找中科院AI4S领域人才',
                         '查找中国科学院从事AI4S领域研究的人才','查找某机构从事任意主题领域的人才']:
            self.assertIsNone(compile_structured(question,[sheet]),question)
        self.assertIsNotNone(compile_structured('查找AI4S领域人才',[sheet]))


class SemanticAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.sheet=TalentSheet('s','f','people',['姓名','领域','当前机构','详细个人简介','所在国家／城市'],[
            {'row':i+2,'talent_id':str(i),'fields':{'姓名':f'Person {i}','领域':'other','当前机构':'Example Institute',
                '详细个人简介':'研发闭环自主实验系统，通过模型选择实验条件并控制机器人。' if i%2==0 else '研究不相关的艺术史材料。',
                '所在国家／城市':'英国'}} for i in range(14)])
        self.question='寻找能自主选择实验并执行科学探索的人才'
        self.plan=TalentPlan(evidence_conditions=['自主科学实验'],topic_condition='自主科学实验',search=SearchSpec(predicates=[
            SearchPredicate(condition='自主科学实验',kind='topic',slot='topic',evidence='自主选择实验',fields=['详细个人简介'],values=['自动化科学发现'])]))
        self.scope=('semantic-admission','actor-a')
        self.index=([str(i) for i in range(14)],np.array([[1.,0.] for _ in range(14)]))

    def planner(self,schema):
        self.assertEqual(schema['phase'],'semantic_candidates')
        decisions=[]
        for candidate in schema['candidates']:
            passage=next((p for p in candidate['passages'] if p['field']=='详细个人简介' and '自主实验' in p['quote']),None)
            decisions.append({'id':candidate['id'],'status':'supported' if passage else 'contradicted','refs':[passage['id']] if passage else []})
        return json.dumps({'decisions':decisions})

    def search(self,planner=None,size=2):
        with patch('app.services.talent_fast_search.ready_index',return_value=(self.index,'ready')), \
             patch('app.services.talent_fast_search.EmbeddingClient.embed_text',return_value=[1.,0.]):
            return json.loads(search_talents(self.question,self.plan,[self.sheet],[],planner or self.planner,self.scope,0,size))

    def test_dense_only_candidates_need_semantic_evidence_and_keep_citations(self):
        result=self.search()
        rows=[r for g in result['results'] for r in g['records']]
        self.assertGreater(len(rows),0)
        self.assertLessEqual(len(rows),2)
        self.assertTrue(all('闭环自主实验' in r['fields']['检索依据'] for r in rows))
        self.assertNotIn('_semantic',result)
        self.assertTrue(result['pagination']['has_more'])
        self.assertFalse(result['coverage']['complete'])
        self.assertIsNone(load_result(result['snapshot_id'],('other-user',),self.question,result['plan']))

    def test_pagination_advances_evidence_queue_without_retrieval_or_duplicate_people(self):
        first=self.search(size=3)
        with patch('app.services.talent_search.read_talent_sheets',side_effect=AssertionError('No reread')), \
             patch('app.services.talent_fast_search.EmbeddingClient.embed_text',side_effect=AssertionError('No re-embedding')):
            second=json.loads(talent_context(self.question,[],self.planner,saved_plan=TalentPlan.model_validate(first['plan']),
                snapshot_id=first['snapshot_id'],snapshot_scope=self.scope,offset=first['pagination']['returned'],max_results=3))
        original={r['excel_row'] for g in first['results'] for r in g['records']}
        following={r['excel_row'] for g in second['results'] for r in g['records']}
        self.assertGreater(len(following),0)
        self.assertFalse(original&following)
        self.assertGreater(second['semantic_status']['checked'],first['semantic_status']['checked'])

    def test_top_five_fills_across_batches_and_continuation_returns_remainder(self):
        first=self.search(size=5)
        self.assertEqual(first['pagination']['returned'],5)
        second=json.loads(talent_context(self.question,[],self.planner,
            saved_plan=TalentPlan.model_validate(first['plan']),snapshot_id=first['snapshot_id'],
            snapshot_scope=self.scope,offset=5,max_results=5))
        self.assertEqual(second['pagination']['returned'],2)
        self.assertFalse(second['pagination']['has_more'])
        original={r['excel_row'] for g in first['results'] for r in g['records']}
        following={r['excel_row'] for g in second['results'] for r in g['records']}
        self.assertFalse(original&following)

    def test_fewer_than_five_exhausts_candidates_and_returns_actual_matches(self):
        for row in self.sheet.rows:
            if row['row'] not in (2,14):row['fields']['详细个人简介']='研究不相关的艺术史材料。'
        result=self.search(size=5)
        self.assertEqual(result['pagination']['returned'],2)
        self.assertEqual(result['semantic_status']['pending'],0)
        self.assertFalse(result['pagination']['has_more'])

    def test_no_match_has_friendly_notice_and_exhausts_candidates(self):
        def reject(schema):
            return json.dumps({'decisions':[{'id':c['id'],'status':'contradicted',
                'refs':[c['passages'][0]['id']]} for c in schema['candidates']]})
        result=self.search(reject,size=5)
        self.assertEqual(result['pagination']['returned'],0)
        self.assertFalse(result['pagination']['has_more'])
        from app.services.talent_answer import render_search_answer
        self.assertIn('未找到符合',render_search_answer(result,[]))

    def test_page_call_allowance_is_finite_and_restored(self):
        from app.core.limits import claim_model_input,semantic_page_calls
        from app.core.security import usage_counter
        counter={'dispatched':4}
        token=usage_counter.set(counter)
        try:
            with semantic_page_calls(3):
                for _ in range(3):claim_model_input([])
                with self.assertRaises(ValueError):claim_model_input([])
            self.assertNotIn('model_call_limit',counter)
            with self.assertRaises(ValueError):claim_model_input([])
        finally:usage_counter.reset(token)

    def test_timeout_and_fabricated_evidence_do_not_become_negative_facts_or_matches(self):
        for planner in [Mock(side_effect=TimeoutError('deadline')),
                        lambda data:json.dumps({'decisions':[{'id':c['id'],'status':'supported','refs':[999]} for c in data['candidates']]})]:
            result=self.search(planner)
            self.assertEqual(result['matched'],0)
            self.assertGreater(result['semantic_status']['unknown'],0)
            from app.services.talent_answer import render_search_answer
            self.assertIn('语义证据尚未确认',render_search_answer(result,[]))

    def test_explicit_total_limit_is_respected_after_semantic_admission(self):
        self.plan.result_limit=1
        result=self.search(size=5)
        self.assertEqual(result['matched'],1)
        self.assertEqual(result['pagination']['returned'],1)
        self.assertFalse(result['pagination']['has_more'])

    def test_service_failure_stops_without_claiming_no_matches(self):
        planner=Mock(side_effect=TimeoutError('deadline'))
        result=self.search(planner,size=5)
        self.assertEqual(planner.call_count,1)
        self.assertGreater(result['semantic_status']['pending'],0)
        from app.services.talent_answer import render_search_answer
        answer=render_search_answer(result,[])
        self.assertIn('核验未完成',answer)
        self.assertNotIn('未找到符合',answer)


class IndexPublicationTests(unittest.TestCase):
    setUp=production.ProductionTests.setUp
    tearDown=production.ProductionTests.tearDown
    base=production.ProductionTests.base
    login=production.ProductionTests.login
    submit=production.ProductionTests.submit
    personnel=production.ProductionTests.personnel

    def test_failed_rebuild_preserves_published_index_and_resumes_staged_batches(self):
        self.login();result=self.submit();source_id=result['source_id']
        process_job(self.db,self.db.get(ImportJobModel,result['job']['id']))
        old=list(self.db.scalars(select(KnowledgeChunkModel.id).where(KnowledgeChunkModel.source_id==source_id)))
        talent=self.db.scalar(select(TalentModel).where(TalentModel.source_id==source_id))
        fields=json.loads(talent.raw_data_json);fields['详细个人简介']='研究蛋白质结构预测和科学建模。'*80
        talent.raw_data_json=json.dumps(fields,ensure_ascii=False)
        index=self.db.get(SourceIndexModel,source_id);index.revision+=1;index.edited=True;self.db.commit()
        job=enqueue(self.db,source_id,self.base_id)
        with patch.object(settings,'embedding_api_url','https://fixture.invalid/v1'),patch.object(settings,'embedding_batch_size',1), \
             patch.object(settings,'embedding_index_pause',0),patch.object(EmbeddingClient,'embed_texts',side_effect=[[[1.,0.]],TimeoutError('upstream')]):
            with self.assertRaises(TimeoutError):process_job(self.db,job)
            self.assertEqual(list(self.db.scalars(select(KnowledgeChunkModel.id).where(KnowledgeChunkModel.source_id==source_id))),old)
            self.assertNotEqual(index.revision,index.indexed_revision)
        with patch.object(settings,'embedding_api_url','https://fixture.invalid/v1'),patch.object(settings,'embedding_batch_size',1), \
             patch.object(settings,'embedding_index_pause',0),patch.object(EmbeddingClient,'embed_texts',return_value=[[1.,0.]]) as send:
            process_job(self.db,job)
            self.assertEqual(job.status,'done')
            self.assertEqual(send.call_count,job.total-1)
            current=list(self.db.scalars(select(KnowledgeChunkModel.id).where(KnowledgeChunkModel.source_id==source_id)))
            self.assertFalse(set(current)&set(old))
            self.assertEqual(len(current),self.db.query(KnowledgeChunkEmbeddingModel).filter(KnowledgeChunkEmbeddingModel.chunk_id.in_(current)).count())
            self.assertEqual(index.indexed_revision,index.revision)

    def test_unchanged_field_vectors_are_reused_after_an_edit(self):
        self.login();result=self.submit();job=self.db.get(ImportJobModel,result['job']['id'])
        sent=[]
        def embed(texts):
            sent.extend(texts);return [[1.,0.] for _ in texts]
        with patch.object(settings,'embedding_api_url','https://fixture.invalid/v1'),patch.object(settings,'embedding_index_pause',0),patch.object(EmbeddingClient,'embed_texts',side_effect=embed):
            process_job(self.db,job)
            self.assertGreaterEqual(len(sent),1);sent.clear()
            talent=self.db.scalar(select(TalentModel).where(TalentModel.source_id==result['source_id']))
            fields=json.loads(talent.raw_data_json);fields['代表成果']='新增的科研成果原文'
            talent.raw_data_json=json.dumps(fields,ensure_ascii=False)
            index=self.db.get(SourceIndexModel,result['source_id']);index.revision+=1;index.edited=True;self.db.commit()
            process_job(self.db,enqueue(self.db,result['source_id'],self.base_id))
            self.assertEqual(len(sent),1)
            self.assertIn('新增的科研成果原文',sent[0])

    def test_duplicate_name_requires_disambiguation_then_resumes_original_question(self):
        self.login();book=Workbook();sheet=book.active
        sheet.append(['姓名','当前机构','代表成果'])
        sheet.append(['测试甲','Institute A','完成蛋白质结构预测系统'])
        sheet.append(['测试甲','Institute B','完成机器人导航系统'])
        buffer=io.BytesIO();book.save(buffer)
        result=self.submit(buffer.getvalue());process_job(self.db,self.db.get(ImportJobModel,result['job']['id']))
        history=[];prompts=[]
        def model(config,messages,model,key):
            if messages[0].content.startswith('将用户本轮人才搜索意图'):
                data=json.loads(messages[-1].content)
                value={'answer_mode':'explain','facets':[{'slot':'person_name','values':['测试甲'],'evidence':'测试甲'}]} if '成果' in data['question'] else {'facets':[{'slot':'current_institution','values':['Institute A'],'evidence':'Institute A'}]}
            elif messages[0].content.startswith('检查一次人才查询条件变更'):value={'verdict':'supported'}
            else:
                prompts.append(messages[-1].content)
                self.assertNotIn('Institute B',messages[-1].content)
                return ChatResult(content='原文成果为蛋白质结构预测。（Chunk 1）',usage=TokenUsage())
            return ChatResult(content=json.dumps(value),usage=TokenUsage())
        with patch.object(OpenAICompatibleProvider,'chat',side_effect=model):
            for question in ['测试甲的研究成果是什么','只看Institute A']:
                response=self.client.post('/api/knowledge/ask',json={'question':question,'knowledge_base_id':self.base_id,'history':history})
                self.assertEqual(response.status_code,200,response.text);data=response.json()
                history.append({'question':question,'answer':data['answer'],'query_state':data.get('query_state')})
            self.assertIn('同名',history[0]['answer'])
            self.assertTrue(data['sources'])
            self.assertEqual(data['query_state']['plan']['document_question'],'测试甲的研究成果是什么')
            self.assertEqual(len(prompts),1)

    def test_named_lookup_and_explanation_remain_scoped_across_followups(self):
        self.login();book=Workbook();sheet=book.active
        sheet.append(['姓名','当前机构','领域','详细个人简介','代表成果','创业／项目经历'])
        sheet.append(['测试甲','Institute A','AI4S','研究蛋白质结构建模','完成蛋白质结构预测系统','科研自动化平台项目'])
        sheet.append(['测试乙','Institute B','robotics','研究移动机器人','完成移动控制系统','机器人导航项目'])
        buffer=io.BytesIO();book.save(buffer)
        result=self.submit(buffer.getvalue());process_job(self.db,self.db.get(ImportJobModel,result['job']['id']))
        base=self.base_id;history=[];final_prompts=[]
        def model(config,messages,model,key):
            if messages[0].content.startswith('将用户本轮人才搜索意图'):
                data=json.loads(messages[-1].content)
                value={'answer_mode':'explain','use_previous_results':True} if data['question'].startswith('他') else {
                    'answer_mode':'explain','facets':[{'slot':'person_name','values':['测试甲'],'evidence':'测试甲'}]}
            elif messages[0].content.startswith('检查一次人才查询条件变更'):
                value={'verdict':'supported'}
            else:
                final_prompts.append(messages[-1].content)
                self.assertNotIn('Institute B',messages[-1].content)
                self.assertNotIn('机器人导航项目',messages[-1].content)
                return ChatResult(content='测试甲的原文资料涉及蛋白质结构预测和科研平台项目。（Chunk 1）',usage=TokenUsage())
            return ChatResult(content=json.dumps(value),usage=TokenUsage())
        with patch.object(OpenAICompatibleProvider,'chat',side_effect=model):
            for question in ['测试甲的研究成果是什么','他还有哪些项目']:
                response=self.client.post('/api/knowledge/ask',json={'question':question,'knowledge_base_id':base,'history':history})
                self.assertEqual(response.status_code,200,response.text)
                data=response.json();self.assertTrue(data['sources'],data)
                self.assertEqual(data['row_sources'],[])
                self.assertEqual(data['query_state']['plan']['intent'],'document')
                self.assertTrue(all('测试甲' in s['content'] and '测试乙' not in s['content'] for s in data['sources']))
                history.append({'question':question,'answer':data['answer'],'query_state':data['query_state']})
            named=self.client.post('/api/knowledge/ask',json={'question':'查找测试乙','knowledge_base_id':base,'history':history})
            self.assertEqual(named.status_code,200,named.text)
            self.assertEqual([r['fields']['姓名'] for r in named.json()['row_sources']],['测试乙'])
        self.assertEqual(len(final_prompts),2)


class CompositeQueryApiTests(unittest.TestCase):
    setUp=workspace.WorkspaceTests.setUp
    tearDown=workspace.WorkspaceTests.tearDown
    base=workspace.WorkspaceTests.base

    def test_dense_semantics_flow_uses_bounded_protocol_and_original_quotes(self):
        from app.ai.base import json_request_timeout,json_max_output_tokens
        base=self.base();book=Workbook();sheet=book.active
        sheet.append(['姓名','详细个人简介']);sheet.append(['A','研发闭环自主实验系统，控制机器人实施实验。'])
        buffer=io.BytesIO();book.save(buffer)
        uploaded=self.client.post(f'/api/knowledge/bases/{base}/upload',files={'file':('people.xlsx',buffer.getvalue(),'application/octet-stream')}).json()
        source_id=uploaded['source']['id']
        roster=TalentSheet(source_id,'people.xlsx','Sheet',['姓名','详细个人简介'],[
            {'row':2,'talent_id':'person','fields':{'姓名':'A','详细个人简介':'研发闭环自主实验系统，控制机器人实施实验。'}}])
        seen=[]
        def model(config,messages,model,key):
            payload=json.loads(messages[-1].content);phase=payload['schema'].get('phase');seen.append(phase)
            if phase=='semantic_candidates':
                self.assertEqual(json_max_output_tokens.get(),256)
                self.assertLessEqual(len(payload['schema']['candidates']),2)
                self.assertEqual(json_request_timeout.get(),settings.talent_semantic_timeout)
                candidate=payload['schema']['candidates'][0]
                proof=next(p for p in candidate['passages'] if p['field']=='详细个人简介')
                result={'decisions':[{'id':candidate['id'],'status':'supported','refs':[proof['id']]}]}
            else:result={'facets':[{'slot':'topic','values':['自动化科学发现'],'evidence':'自己制定并执行实验'}]}
            return ChatResult(content=json.dumps(result),usage=TokenUsage())
        with patch('app.services.talent_search.read_talent_sheets',return_value=([roster],[])), \
             patch('app.services.talent_fast_search.ready_index',return_value=((['person'],np.array([[1.,0.]])),'ready')), \
             patch.object(EmbeddingClient,'embed_text',return_value=[1.,0.]),patch.object(OpenAICompatibleProvider,'chat',side_effect=model):
            result=self.client.post('/api/knowledge/ask/stream',json={'question':'找能自己制定并执行实验的人才','knowledge_base_id':base})
        self.assertEqual(result.status_code,200,result.text)
        self.assertIn('研发闭环自主实验系统',result.text)
        self.assertEqual(seen,[None,'semantic_candidates'])
        self.assertNotIn('"_semantic"',result.text)

    def test_institution_and_topic_are_independent_with_aliases_and_citations(self):
        base=self.base();book=Workbook();sheet=book.active
        sheet.append(['姓名','领域','当前机构','研究方向'])
        sheet.append(['A','AI4S','中科院某研究所','科学建模'])
        sheet.append(['B','AI for Science','某研究所, Chinese Academy of Sciences','计算材料'])
        sheet.append(['C','other','中国科学院某研究所','无关方向'])
        sheet.append(['D','AI4S','Other Institute','科学建模'])
        output=io.BytesIO();book.save(output)
        self.client.post(f'/api/knowledge/bases/{base}/upload',files={'file':('people.xlsx',output.getvalue(),'application/octet-stream')})
        output={'facets':[{'slot':'current_institution','values':['中国科学院'],'evidence':'中科院'},
                          {'slot':'topic','values':['AI4S'],'evidence':'AI4s'}]}
        with patch.object(OpenAICompatibleProvider,'chat',return_value=ChatResult(content=json.dumps(output),usage=TokenUsage())) as chat, \
             patch('app.services.talent_fast_search.ready_index',return_value=(None,'disabled')):
            response=self.client.post('/api/knowledge/ask',json={'question':'查找中科院从事AI4s领域的人才','knowledge_base_id':base})
        self.assertEqual(response.status_code,200,response.text)
        data=response.json()
        self.assertEqual({r['fields']['姓名'] for r in data['row_sources']},{'A','B'})
        self.assertEqual({p['slot'] for p in data['query_state']['plan']['search']['predicates']},{'topic','current_institution'})
        self.assertTrue(all(r['source_id'] and r['excel_row'] for r in data['row_sources']))
        self.assertEqual(chat.call_count,1)


class EmbeddingIntegrityTests(unittest.TestCase):
    def test_bad_indexes_dimensions_and_nonfinite_vectors_are_rejected(self):
        import httpx
        client=EmbeddingClient(EmbeddingConfig('https://fixture.invalid/v1',None,'test-integrity'))
        cases=[{'data':[{'index':0,'embedding':[1,0]},{'index':0,'embedding':[0,1]}]},
               {'data':[{'index':0,'embedding':[1,0]}]},
               {'data':[{'index':0,'embedding':[1,0]},{'index':1,'embedding':[1]}]},
               {'data':[{'index':0,'embedding':[0,0]},{'index':1,'embedding':[1,0]}]}]
        for data in cases:
            transport=httpx.MockTransport(lambda req:httpx.Response(200,json=data))
            with patch.object(client,'_client',side_effect=lambda:httpx.Client(base_url='https://fixture.invalid/v1',transport=transport)),self.assertRaises(RuntimeError):
                client._embed_texts(['first','second'])
        data={'data':[{'index':1,'embedding':[0,1]},{'index':0,'embedding':[1,0]}]}
        transport=httpx.MockTransport(lambda req:httpx.Response(200,json=data))
        with patch.object(client,'_client',side_effect=lambda:httpx.Client(base_url='https://fixture.invalid/v1',transport=transport)):
            self.assertEqual(client._embed_texts(['first','second'])[0],[[1.,0.],[0.,1.]])

    def test_normal_concurrent_queries_do_not_open_a_failure_circuit(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from uuid import uuid4
        barrier=Barrier(2)
        client=EmbeddingClient(EmbeddingConfig('https://fixture.invalid/v1',None,'parallel-'+str(uuid4())))
        def send(texts):barrier.wait(timeout=2);return [[1.,0.]]
        with patch.object(client,'embed_texts',side_effect=send),ThreadPoolExecutor(max_workers=2) as pool:
            tasks=[pool.submit(client.embed_text,text) for text in ('first','second')]
            self.assertEqual([t.result(timeout=3) for t in tasks],[[1.,0.],[1.,0.]])


class ResultScopeContracts(unittest.TestCase):
    def test_materialized_page_scope_does_not_shrink_when_a_country_is_replaced(self):
        roster=TalentSheet('s','f','p',['姓名','所在国家／城市'],[
            {'row':2,'fields':{'姓名':'A','所在国家／城市':'英国'}},
            {'row':3,'fields':{'姓名':'B','所在国家／城市':'美国'}},
            {'row':4,'fields':{'姓名':'C','所在国家／城市':'美国'}}])
        planner=SimpleNamespace(previous_snapshot={'plan':{},'result_order':[['s','p',2],['s','p',3],['s','p',4]]},
                                previous_page_keys=[['s','p',2],['s','p',3]])
        plan=TalentPlan(intent='aggregate',operation='count',result_scope='previous_page',scope_explicit=True)
        scope=('page-scope-test',)
        result=json.loads(search_talents('当前页多少人',plan,[roster],[],planner,scope,0,5))
        self.assertEqual(result['aggregate']['records'],2)
        planner.previous_snapshot=load_result(result['snapshot_id'],scope,'当前页多少人',result['plan'])
        for region in ['英国','美国']:
            narrowed=plan.model_copy(update={'scope_explicit':False,'evidence_conditions':[region],
                'search':SearchSpec(predicates=[SearchPredicate(condition=region,kind='metadata',slot='current_region',fields=['@current_region'],op='equals_any',values=[region])])})
            result=json.loads(search_talents(region,narrowed,[roster],[],planner,scope,0,5))
            self.assertEqual(result['aggregate']['records'],1)
            self.assertNotIn('_scope_keys',result)
            planner.previous_snapshot=load_result(result['snapshot_id'],scope,region,result['plan'])
        from app.services.talent_context_update import ContextChangeUnresolved
        with self.assertRaises(ContextChangeUnresolved):search_talents('本页多少',plan,[roster],[],None,scope,0,5)

    def test_semantic_verdict_cache_is_scoped_to_conditions_and_actor(self):
        from app.services.talent_semantic_gate import check_candidates
        candidate={'fields':{'详细个人简介':'研发闭环自主实验系统。'}}
        def planner(data):
            return json.dumps({'decisions':[{'id':'0','status':'supported','refs':[0]}]})
        planner.cache_namespace='proof-cache-contract'
        first=check_candidates('自主实验',['自主实验'],[candidate],planner)
        cached=Mock(side_effect=AssertionError('cached verdict must avoid a second model call'))
        cached.cache_namespace=planner.cache_namespace
        second=check_candidates('自主实验',['自主实验'],[candidate],cached)
        self.assertEqual(first,second)


class CompoundTopicContracts(unittest.TestCase):
    def test_recall_expansions_do_not_turn_a_compound_requirement_into_or(self):
        from app.services.talent_semantic_gate import direct_topic
        predicate=SearchPredicate(condition='运用机器学习推动科学发现',kind='topic',slot='topic',
            evidence='运用机器学习推动科学发现',fields=['详细个人简介'],values=['机器学习','科学发现'])
        self.assertFalse(direct_topic({'详细个人简介':'研究机器学习广告投放。'},predicate,predicate.evidence))
        self.assertTrue(direct_topic({'详细个人简介':'运用机器学习推动科学发现。'},
            predicate.model_copy(update={'values':['运用机器学习推动科学发现']}),predicate.evidence))


class RetrievalIndexContracts(unittest.TestCase):
    def test_existing_tables_gain_covering_indexes_idempotently(self):
        from sqlalchemy import create_engine,text,inspect
        from app.db.retrieval_schema import upgrade_retrieval_indexes
        engine=create_engine('sqlite://')
        with engine.begin() as db:
            db.execute(text('CREATE TABLE knowledge_chunks(id TEXT PRIMARY KEY,source_id TEXT,chunk_index INTEGER)'))
            db.execute(text('CREATE TABLE knowledge_chunk_embeddings(chunk_id TEXT PRIMARY KEY,embedding_model TEXT,embedding_dim INTEGER,embedding_json TEXT)'))
            upgrade_retrieval_indexes(db);upgrade_retrieval_indexes(db)
            self.assertIn('ix_knowledge_chunks_source_index',{i['name'] for i in inspect(db).get_indexes('knowledge_chunks')})
            plan=db.execute(text("EXPLAIN QUERY PLAN SELECT count(*) FROM knowledge_chunk_embeddings e JOIN knowledge_chunks c ON c.id=e.chunk_id WHERE c.source_id='s' AND e.embedding_model='bge-m3' AND e.embedding_dim=1024")).all()
            self.assertIn('COVERING INDEX ix_chunk_embeddings_model_dimension',str(plan))
            self.assertNotIn('SCAN e',str(plan))
        engine.dispose()


class SemanticTransportContracts(unittest.TestCase):
    def test_fenced_json_is_normalized_but_duplicate_keys_fail_closed(self):
        from app.services.talent_semantic_gate import check_candidates
        candidate={'fields':{'详细个人简介':'研发闭环自主实验系统。'}}
        payload='{"decisions":[{"id":"0","status":"supported","refs":[0]}]}'
        good=check_candidates('自主实验',['自主实验'],[candidate],lambda _: '```json\n'+payload+'\n```')
        self.assertEqual(good[0][1]['status'],'supported')
        duplicate=payload.replace('"status":"supported"','"status":"contradicted","status":"supported"')
        bad=check_candidates('自主实验',['自主实验'],[candidate],lambda _:duplicate)
        self.assertEqual(bad[0][1]['status'],'unknown')
