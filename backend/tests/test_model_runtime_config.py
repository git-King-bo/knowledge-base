import unittest
from unittest.mock import patch
from cryptography.fernet import Fernet
from fastapi import HTTPException
from sqlalchemy import create_engine,select
from sqlalchemy.orm import Session
from app.core.config import Settings,settings
from app.core.security import validate_provider_url,decrypt_secret
from app.db.session import Base
from app.db.models import AIProviderModel,AIModelModel
from app.db.init_db import seed_db

class ModelRuntimeConfigTests(unittest.TestCase):
    def test_full_endpoint_normalization(self):
        config=Settings(_env_file=None,AGENT_DEFAULT_API_URL='http://192.168.0.186:8000/v1/chat/completions',AGENT_EMBEDDING_API_URL='http://103.238.140.158:8100/v1/embeddings',AGENT_EMBEDDING_DIMENSION=1024)
        self.assertEqual(config.default_api_url,'http://192.168.0.186:8000/v1')
        self.assertEqual(config.embedding_api_url,'http://103.238.140.158:8100/v1')
        self.assertEqual(config.embedding_dimensions,1024)

    def test_http_exception_is_exact_origin_and_still_enforces_host_allowlist(self):
        with patch.multiple(settings,app_env='production',provider_allowed_hosts='192.168.0.186,103.238.140.158,other.example',provider_http_origins='http://192.168.0.186:8000,http://103.238.140.158:8100',allow_private_providers=False):
            self.assertEqual(validate_provider_url('http://192.168.0.186:8000/v1'),'http://192.168.0.186:8000/v1')
            self.assertEqual(validate_provider_url('http://103.238.140.158:8100/v1'),'http://103.238.140.158:8100/v1')
            for url in ['http://192.168.0.186:8001/v1','http://192.168.0.187:8000/v1','http://other.example/v1','http://localhost:8000/v1','http://user:password@192.168.0.186:8000/v1']:
                with self.subTest(url=url),self.assertRaises(HTTPException):validate_provider_url(url)
            with patch.object(settings,'provider_allowed_hosts','other.example'):
                with self.assertRaises(HTTPException):validate_provider_url('http://192.168.0.186:8000/v1')

    def test_file_managed_provider_updates_key_model_and_default_on_restart(self):
        engine=create_engine('sqlite:///:memory:');Base.metadata.create_all(engine)
        try:
            with Session(engine) as db,patch.multiple(settings,sync_env_provider=True,default_api_url='http://192.168.0.186:8000/v1',default_api_key='test-key-one',default_api_model='qwen3.8',provider_allowed_hosts='192.168.0.186',provider_http_origins='http://192.168.0.186:8000',app_env='production',encryption_key=Fernet.generate_key().decode()):
                seed_db(db)
                provider=db.get(AIProviderModel,'provider-agent-default')
                self.assertEqual(provider.default_model,'qwen3.8')
                self.assertEqual(decrypt_secret(provider.api_key_encrypted),'test-key-one')
                with patch.multiple(settings,default_api_key='test-key-two',default_api_model='replacement-model'):seed_db(db)
                self.assertEqual(decrypt_secret(provider.api_key_encrypted),'test-key-two')
                self.assertEqual(db.get(AIModelModel,'model-agent-default').name,'replacement-model')
                self.assertEqual([p.id for p in db.scalars(select(AIProviderModel).where(AIProviderModel.is_default.is_(True)))],['provider-agent-default'])
        finally:engine.dispose()

    def test_dimension_mismatch_is_rejected(self):
        import httpx
        from app.services.embeddings import EmbeddingClient
        with patch.multiple(settings,embedding_model='bge-m3',embedding_api_url='http://example.test/v1',embedding_dimensions=1024):
            client=EmbeddingClient()
            for size in (1024,3):
                transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'data':[{'index':0,'embedding':[0.1]*size}]}))
                with patch.object(client,'_client',side_effect=lambda:httpx.Client(base_url='http://example.test/v1',transport=transport)):
                    if size==1024:self.assertEqual(len(client._embed_texts(['test'])[0][0]),1024)
                    else:
                        with self.assertRaisesRegex(RuntimeError,'dimensions'):client._embed_texts(['test'])
