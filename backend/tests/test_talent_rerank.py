import unittest
from unittest.mock import patch,Mock
import httpx
from app.core.config import settings
from app.services.talent_rerank import rerank


class RerankTests(unittest.TestCase):
    def test_disabled_has_no_network_calls(self):
        with patch.object(settings,'rerank_api_url',''),patch('httpx.Client') as client:
            self.assertEqual(rerank('q',['a','b']),([0,1],'not_configured'))
            client.assert_not_called()

    def test_valid_order_and_invalid_duplicate_and_timeout(self):
        for result,expected in [({'results':[{'index':0,'relevance_score':.1},{'index':1,'relevance_score':.9}]},([1,0],'ready')),
                                ({'results':[{'index':0,'relevance_score':.1},{'index':0,'relevance_score':.9}]},([0,1],'unavailable')),
                                (httpx.ReadTimeout('timeout'),([0,1],'unavailable'))]:
            response=Mock();response.json.return_value=result
            with patch.object(settings,'rerank_api_url','https://example.test/rerank'),patch.object(settings,'rerank_model','ranker'), \
                 patch('app.services.talent_rerank.validate_provider_url'),patch('app.services.talent_rerank.httpx.Client') as client:
                if isinstance(result,Exception):client.return_value.__enter__.return_value.post.side_effect=result
                else:client.return_value.__enter__.return_value.post.return_value=response
                self.assertEqual(rerank('q',['a','b']),expected)
