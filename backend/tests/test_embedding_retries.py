import unittest
from unittest.mock import patch
import httpx
from app.services.embeddings import EmbeddingClient, EmbeddingConfig


class EmbeddingRetriesTests(unittest.TestCase):
    def setUp(self):
        self.client = EmbeddingClient(EmbeddingConfig('http://example.test/v1', None, 'test'))

    def test_batch_transient_failure_retries_with_backoff(self):
        with patch.object(self.client, '_embed_once', side_effect=[httpx.ReadTimeout('timeout'), [[1.0]]]) as call, patch('app.services.embeddings.sleep') as sleep:
            self.assertEqual(self.client.embed_texts(['test']), [[1.0]])
            self.assertEqual(call.call_count, 2)
            sleep.assert_called_once_with(1.0)

    def test_query_does_not_retry(self):
        with patch.object(self.client, '_embed_once', side_effect=httpx.ReadTimeout('timeout')) as call, patch('app.services.embeddings.sleep') as sleep:
            with self.assertRaises(httpx.ReadTimeout):
                self.client.embed_text('test')
            self.assertEqual(call.call_count, 1)
            sleep.assert_not_called()

    def test_auth_failure_does_not_retry(self):
        request = httpx.Request('POST', 'http://example.test/v1/embeddings')
        response = httpx.Response(403, request=request)
        error = httpx.HTTPStatusError('denied', request=request, response=response)
        with patch.object(self.client, '_embed_once', side_effect=error) as call:
            with self.assertRaises(httpx.HTTPStatusError):
                self.client.embed_texts(['test'])
            self.assertEqual(call.call_count, 1)

    def test_retry_count_is_bounded(self):
        with patch.object(self.client, '_embed_once', side_effect=httpx.ConnectError('offline')) as call, patch('app.services.embeddings.sleep'):
            with self.assertRaises(httpx.ConnectError):
                self.client.embed_texts(['test'])
            self.assertEqual(call.call_count, 4)
