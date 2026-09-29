import hashlib
import io
import json
from pathlib import Path
from unittest.mock import patch
import unittest
from openpyxl import Workbook
from sqlalchemy import select, func
import test_workspace as fixtures
from app.core.config import settings
from app.core.security import password_hash, now, decrypt_secret
from app.db.models import UserModel, BaseAccessModel, TalentModel, ImportJobModel, AIProviderModel, KnowledgeSourceModel, SourceIndexModel
from app.services.import_jobs import process_job

class ProductionTests(unittest.TestCase):
    base = fixtures.WorkspaceTests.base
    upload = fixtures.WorkspaceTests.upload
    def setUp(self):
        from app.core.security import _rates
        _rates.clear()
        fixtures.WorkspaceTests.setUp(self)
        self.base_id=self.base('Team A')
        self.other=self.base('Team B')
        for name,role in [('admin','admin'),('editor','editor'),('viewer','viewer')]:
            self.db.add(UserModel(id=name,username=name,password_hash=password_hash('test-password-123'),role=role,enabled=True,created_at=now()))
        self.db.add(BaseAccessModel(base_id=self.base_id,user_id='editor',role='editor'))
        self.db.add(BaseAccessModel(base_id=self.base_id,user_id='viewer',role='viewer'))
        self.db.commit()
        self.auth=patch.object(settings,'auth_enabled',True);self.auth.start()
        self.client.headers['X-Requested-With']='knowledge-base'
    def tearDown(self):
        self.auth.stop();fixtures.WorkspaceTests.tearDown(self)
    def login(self,name='admin'):
        self.client.cookies.clear()
        response=self.client.post('/api/auth/login',json={'username':name,'password':'test-password-123'})
        self.assertEqual(response.status_code,200,response.text)
    def personnel(self):
        w=Workbook();w.active.append(['姓名','当前机构','领域']);w.active.append(['测试人员','机构A','人工智能'])
        out=io.BytesIO();w.save(out);w.close();return out.getvalue()
    def submit(self,raw=None):
        r=self.client.post('/api/imports/'+self.base_id,files={'file':('talents.xlsx',raw or self.personnel())})
        self.assertEqual(r.status_code,202,r.text);return r.json()
    def test_auth_and_base_isolation(self):
        self.assertEqual(self.client.get('/api/knowledge/bases').status_code,401)
        self.login('viewer')
        self.assertEqual([b['id'] for b in self.client.get('/api/knowledge/bases').json()],[self.base_id])
        self.assertEqual(self.client.get('/api/knowledge/bases/'+self.other+'/sources').status_code,404)
        self.assertEqual(self.client.post('/api/knowledge/bases',json={'name':'denied'}).status_code,403)
        self.assertEqual(self.client.get('/api/usage').status_code,403)
    def test_key_encryption_and_url_change(self):
        self.login()
        r=self.client.post('/api/ai/providers',json={'name':'secure','provider':'openai','base_url':'https://example.com/v1','default_model':'model','api_key':'fixture-secret'})
        self.assertEqual(r.status_code,201,r.text)
        p=self.db.get(AIProviderModel,r.json()['id'])
        self.assertTrue(p.api_key_encrypted.startswith('fernet:'))
        self.assertEqual(decrypt_secret(p.api_key_encrypted),'fixture-secret')
        self.assertNotIn('fixture-secret',r.text)
        self.assertEqual(self.client.put('/api/ai/providers/'+p.id,json={'base_url':'https://other.example/v1'}).status_code,400)
        self.assertEqual(self.client.put('/api/ai/providers/'+p.id,json={'base_url':'http://127.0.0.1/v1','api_key':'new'}).status_code,400)
    def test_import_resume_reuse_and_talent_edit(self):
        self.login('editor')
        raw=self.personnel();first=self.submit(raw)
        job=self.db.get(ImportJobModel,first['job']['id']);process_job(self.db,job)
        self.assertEqual(job.status,'done')
        again=self.submit(raw);self.assertTrue(again['reused'])
        self.assertEqual(first['source_id'],again['source_id'])
        self.assertEqual(self.db.scalar(select(func.count()).select_from(TalentModel)),1)
        listing=self.client.get('/api/talents').json();tid=listing['items'][0]['id']
        detail=self.client.get('/api/talents/'+tid).json()
        r=self.client.put('/api/talents/'+tid,json={'fields':{'当前机构':'新机构'},'revision':detail['revision']})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.client.get('/api/talents/'+tid).json()['fields']['当前机构'],'新机构')
        self.assertFalse(self.client.post('/api/imports/'+self.base_id+'/reuse',json={'sha256':hashlib.sha256(raw).hexdigest()}).json()['reused'])
        source=self.db.get(KnowledgeSourceModel,first['source_id'])
        from app.services.talent_search import read_talent_sheets
        self.assertEqual(read_talent_sheets([source])[0][0].rows[0]['fields']['当前机构'],'新机构')
        self.assertEqual(self.client.put('/api/talents/'+tid,json={'fields':{'当前机构':'overwrite'},'revision':detail['revision']}).status_code,409)
    def test_reuse_does_not_leak_private_sources(self):
        self.login();raw=self.personnel();r=self.submit(raw);process_job(self.db,self.db.get(ImportJobModel,r['job']['id']))
        self.db.query(BaseAccessModel).filter_by(user_id='editor').delete();self.db.add(BaseAccessModel(base_id=self.other,user_id='editor',role='editor'));self.db.commit()
        self.login('editor')
        result=self.client.post('/api/imports/'+self.other+'/reuse',json={'sha256':hashlib.sha256(raw).hexdigest()})
        self.assertEqual(result.json(),{'reused':False})
        self.assertEqual(self.client.get('/api/talents').json()['total'],0)
    def test_conversation_ownership(self):
        self.login('editor')
        data={'title':'test','messages':[],'favorite':True}
        self.assertEqual(self.client.put('/api/conversations/test',json=data).status_code,200)
        self.login('viewer')
        self.assertEqual(self.client.get('/api/conversations/test').status_code,404)
        self.assertEqual(self.client.put('/api/conversations/test',json=data).status_code,404)
        self.assertEqual(self.client.put('/api/conversations/own',json=data).status_code,200)
    def test_cancel_retry_and_trash(self):
        self.login();r=self.submit();jid=r['job']['id']
        self.assertEqual(self.client.post('/api/jobs/'+jid+'/cancel').json()['status'],'cancelled')
        self.assertEqual(self.client.post('/api/jobs/'+jid+'/retry').json()['status'],'queued')
        self.client.post('/api/jobs/'+jid+'/cancel')
        self.assertEqual(self.client.delete('/api/knowledge/bases/'+self.base_id).status_code,204)
        self.assertNotIn(self.base_id,[b['id'] for b in self.client.get('/api/knowledge/bases').json()])
        self.assertEqual(self.client.post('/api/trash/'+self.base_id+'/restore').status_code,200)
    def test_csrf_and_role_enforcement(self):
        self.login('viewer');self.client.headers.pop('X-Requested-With')
        self.assertEqual(self.client.post('/api/auth/logout').status_code,403)

    def test_reuse_skips_embedding_calls(self):
        self.login();raw=self.personnel();first=self.submit(raw)
        with patch.object(settings,'embedding_api_url','https://fixture.invalid/v1'), patch('app.services.embeddings.EmbeddingClient.embed_texts',return_value=[[1.0,0.0]]) as embed:
            job=self.db.get(ImportJobModel,first['job']['id']);process_job(self.db,job)
            calls=embed.call_count
            self.assertGreater(calls,0)
            self.assertTrue(self.submit(raw)['reused'])
            self.assertEqual(embed.call_count,calls)
    def test_quota_denies_before_model_call(self):
        self.login('viewer')
        with patch.object(settings,'daily_token_budget',1):
            r=self.client.post('/api/ai/chat',json={'messages':[{'role':'user','content':'test'}]})
        self.assertEqual(r.status_code,429)
        self.assertEqual(self.requests,[])
    def test_purge_removes_unshared_data(self):
        self.login();result=self.submit();job=self.db.get(ImportJobModel,result['job']['id']);process_job(self.db,job)
        path=Path(self.db.get(KnowledgeSourceModel,result['source_id']).storage_path)
        self.client.delete('/api/knowledge/bases/'+self.base_id)
        response=self.client.delete('/api/trash/'+self.base_id)
        self.assertEqual(response.status_code,200,response.text)
        self.assertFalse(path.exists())
        self.assertEqual(self.db.scalar(select(func.count()).select_from(TalentModel)),0)

    def test_missing_embedding_usage_does_not_charge_entire_request_reservation(self):
        from app.ai.providers.openai_compatible import OpenAICompatibleProvider
        from app.repositories.sqlite import AIRepository
        from app.db.models import RequestBudgetModel
        original=OpenAICompatibleProvider.chat
        def chat(adapter, *args, **kwargs):
            AIRepository(self.db).create_activity_log(action='embedding',provider_id='embedding',model='disabled',
                request_text='Embedding batch: 1 texts',response_text='',success=False,latency_ms=0)
            return original(adapter,*args,**kwargs)
        self.login()
        with patch.object(settings,'daily_token_budget',12000), patch.object(OpenAICompatibleProvider,'chat',chat):
            for _ in range(3):
                result=self.client.post('/api/ai/chat',json={'messages':[{'role':'user','content':'test'}]})
                self.assertEqual(result.status_code,200,result.text)
        self.db.expire_all()
        row=self.db.get(RequestBudgetModel,('admin',now().date().isoformat()))
        self.assertEqual(row.tokens,375)
        self.assertEqual(row.reserved,0)

    def test_missing_chat_usage_charges_only_dispatched_bound(self):
        import httpx
        from app.ai.providers.openai_compatible import OpenAICompatibleProvider
        from app.db.models import RequestBudgetModel
        transport=httpx.MockTransport(lambda request: httpx.Response(200,json={'choices':[{'message':{'content':'answer'}}]}))
        self.login()
        with patch.object(OpenAICompatibleProvider,'_client',side_effect=lambda config:httpx.Client(base_url=config.base_url,transport=transport)):
            result=self.client.post('/api/ai/chat',json={'messages':[{'role':'user','content':'test'}]})
        self.assertEqual(result.status_code,200,result.text)
        self.db.expire_all()
        row=self.db.get(RequestBudgetModel,('admin',now().date().isoformat()))
        self.assertEqual(row.tokens,4+32+settings.model_max_output_tokens)
        self.assertEqual(row.reserved,0)

    def test_large_input_reservation_denies_before_dispatch_and_releases_hold(self):
        from app.db.models import RequestBudgetModel
        self.login()
        with patch.object(settings,'daily_token_budget',10000):
            result=self.client.post('/api/ai/chat',json={'messages':[{'role':'user','content':'x'*20000}]})
        self.assertNotEqual(result.status_code,200)
        self.assertEqual(self.requests,[])
        self.db.expire_all()
        row=self.db.get(RequestBudgetModel,('admin',now().date().isoformat()))
        self.assertEqual(row.tokens,0)
        self.assertEqual(row.reserved,0)
