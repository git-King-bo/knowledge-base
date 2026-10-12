import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import httpx

from app.services.query_cache import BoundedCache
from app.services.embeddings import EmbeddingClient,EmbeddingConfig,_circuits,_circuit_lock
from app.services.model_batch import run_model_batch
from app.core.security import usage_counter
from app.schemas.ai import ChatMessage
from app.services.talent_evidence import verify_candidates
from app.services.talent_search import TalentPlan

class QueryPerformanceTests(unittest.TestCase):
    def test_cache_is_bounded_versioned_and_returns_isolated_values(self):
        cache=BoundedCache(max_entries=2,ttl=10)
        for version in (1,2,3):cache.put(('user','base',version),{'rows':[version]})
        self.assertIsNone(cache.get(('user','base',1)))
        self.assertIsNone(cache.get(('other-user','base',3)))
        self.assertIsNone(cache.get(('user','other-base',3)))
        value=cache.get(('user','base',3));value['rows'].append('mutated')
        self.assertEqual(cache.get(('user','base',3)),{'rows':[3]})
        with patch('app.services.query_cache.monotonic',return_value=float('inf')):
            self.assertIsNone(cache.get(('user','base',3)))
        cache.put('oversize','x'*cache.max_bytes)
        self.assertIsNone(cache.get('oversize'))

    def test_embedding_denial_cooldown_key_rotation_and_recovery(self):
        with _circuit_lock:_circuits.clear()
        client=EmbeddingClient(EmbeddingConfig('https://test.invalid/v1','key-one','test-circuit'))
        response=httpx.Response(403,request=httpx.Request('POST','https://test.invalid/v1/embeddings'))
        failure=httpx.HTTPStatusError('denied',request=response.request,response=response)
        with patch.object(EmbeddingClient,'embed_texts',side_effect=failure) as send:
            with self.assertRaises(httpx.HTTPStatusError):client.embed_text('first')
            with self.assertRaisesRegex(RuntimeError,'circuit open'):client.embed_text('different')
            self.assertEqual(send.call_count,1)
        client.config.api_key='key-two'
        with patch.object(EmbeddingClient,'embed_texts',return_value=[[1.,0.]]) as send:
            self.assertEqual(client.embed_text('first'),[1.,0.])
            self.assertEqual(client.embed_text('first'),[1.,0.])
            self.assertEqual(send.call_count,1)
        client.config.api_key='key-one'
        with patch('app.services.embeddings.monotonic',return_value=float('inf')),patch.object(EmbeddingClient,'embed_texts',return_value=[[0.,1.]]):
            self.assertEqual(client.embed_text('first'),[0.,1.])

    def test_query_timeout_does_not_shorten_ingestion_timeout(self):
        from app.services.embeddings import _query_mode
        from app.core.config import settings
        client=EmbeddingClient(EmbeddingConfig('https://test.invalid/v1',None,'m'))
        with patch('app.services.embeddings.validate_provider_url'):
            with client._client() as http:self.assertEqual(http.timeout.read,60.)
            token=_query_mode.set(True)
            try:
                with client._client() as http:self.assertEqual(http.timeout.read,settings.embedding_query_timeout)
            finally:_query_mode.reset(token)

    def test_parallel_transport_never_shares_budget_or_logs_from_worker(self):
        main=threading.get_ident();barrier=threading.Barrier(2,timeout=3)
        counter={'dispatched':2};token=usage_counter.set(counter)
        calls=[]
        class Adapter:
            def _chat_reserved(self,config,messages,model,key):
                assert usage_counter.get() is None
                assert threading.get_ident()!=main
                barrier.wait()
                if messages[0].content=='fail':raise TimeoutError('upstream timeout')
                return SimpleNamespace(content='ok')
        def record(messages,result,error,latency):
            self.assertEqual(threading.get_ident(),main)
            calls.append((messages[0].content,result,error))
        try:
            results=run_model_batch(Adapter(),None,[[ChatMessage(role='user',content=x)] for x in ('ok','fail')],'m',None,record)
            self.assertEqual(counter['dispatched'],4)
            self.assertEqual(results[0],'ok');self.assertIsInstance(results[1],TimeoutError)
            self.assertEqual([c[0] for c in calls],['ok','fail'])
        finally:usage_counter.reset(token)

    def test_four_reserved_calls_overlap_in_one_wave(self):
        barrier = threading.Barrier(4, timeout=3)
        token = usage_counter.set({'dispatched':0})
        class Adapter:
            def _chat_reserved(self, *args):
                barrier.wait()
                return SimpleNamespace(content='ok')
        try:
            results = run_model_batch(Adapter(), None,
                [[ChatMessage(role='user', content=str(i))] for i in range(4)],
                'm', None, lambda *args: None)
            self.assertEqual(results, ['ok'] * 4)
        finally:
            usage_counter.reset(token)

    def test_budget_exhaustion_does_not_dispatch_or_log_unreserved_call(self):
        counter={'dispatched':4};token=usage_counter.set(counter)
        try:
            results=run_model_batch(None,None,[[ChatMessage(role='user',content='test')]],'m',None,
                                    lambda *args:self.fail('No dispatch means no usage log'))
            self.assertIsInstance(results[0],ValueError)
            self.assertEqual(counter['dispatched'],4)
        finally:usage_counter.reset(token)

    def test_partial_parallel_failure_retains_success_and_remaining_candidates(self):
        counter={'dispatched':2};token=usage_counter.set(counter)
        plan=TalentPlan(evidence_conditions=['条件'])
        results=[{'records':[{'fields':{'姓名':f'人才{i}'},'excel_row':i+2} for i in range(12)],'matched_records':12}]
        def planner(payload):self.fail('No third call allowed')
        def batch(payloads):
            counter['dispatched']+=2
            return [json.dumps({'decisions':[{'id':r['id'],'checks':[{'status':'supported','refs':[0]}]} for r in payloads[0]['candidates']]}),TimeoutError()]
        planner.batch=batch
        try:
            stats=verify_candidates('query',plan,results,planner,max_calls=2)
            self.assertEqual(stats['supported'],6)
            self.assertEqual(stats['unverified'],6)
            self.assertEqual(stats['model_calls'],2)
            self.assertEqual(len(results[0]['records']),6)
        finally:usage_counter.reset(token)

    def test_verified_cache_reuses_only_valid_known_judgments_and_invalidates_on_data_change(self):
        from app.services.query_cache import verification_cache
        import uuid
        namespace=uuid.uuid4().hex
        calls=[]
        plan=TalentPlan(evidence_conditions=['有关联'])
        def planner(payload):
            calls.append(payload)
            return json.dumps({'decisions':[{'id':r['id'],'checks':[
                {'status':'unknown' if r['fields']['姓名']=='未知人员' else 'supported','refs':[0]}]}
                for r in payload['candidates']]})
        planner.cache_namespace=namespace
        def run(name='已知人员'):
            results=[{'records':[{'fields':{'姓名':name},'excel_row':2},
                                 {'fields':{'姓名':'未知人员'},'excel_row':3}],'matched_records':2}]
            return verify_candidates('有关联的人才',plan,results,planner,max_calls=1)
        self.assertEqual(run()['supported'],1)
        self.assertEqual(len(calls[-1]['candidates']),2)
        self.assertEqual(run()['supported'],1)
        self.assertEqual([r['fields']['姓名'] for r in calls[-1]['candidates']],['未知人员'])
        run('资料已更改')
        self.assertEqual(len(calls[-1]['candidates']),2)
        planner.cache_namespace=namespace+'other-user'
        run()
        self.assertEqual(len(calls[-1]['candidates']),2)

    def test_plan_cache_is_scoped_to_context_and_data_revision(self):
        from app.services.talent_search import TalentSheet,talent_context
        import uuid
        sheet=TalentSheet('source','people.xlsx','人才',['姓名'],[{'row':2,'fields':{'姓名':'甲'}}])
        calls=[]
        def planner(payload):
            calls.append(payload)
            return '{"intent":"filter","match_all":true}'
        planner.cache_namespace=uuid.uuid4().hex
        planner.plan_context_key='first-context'
        planner.requires_context=True
        with patch('app.services.talent_search.read_talent_sheets',return_value=([sheet],[])):
            for _ in range(2):
                talent_context('全部人才',[],planner,snapshot_scope=('user','base','v1'))
            self.assertEqual(len(calls),1)
            planner.plan_context_key='new-context'
            talent_context('全部人才',[],planner,snapshot_scope=('user','base','v1'))
            talent_context('全部人才',[],planner,snapshot_scope=('user','base','v2'))
            self.assertEqual(len(calls),3)
