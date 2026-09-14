import asyncio
import json
import unittest
from unittest.mock import patch

import httpx
import test_workspace as workspace
from app.ai.providers.openai_compatible import OpenAICompatibleProvider
from app.api.routes.knowledge import stream_knowledge
from app.repositories.sqlite import AIRepository
from app.schemas.knowledge import AskRequest


class StreamingTests(unittest.TestCase):
    setUp = workspace.WorkspaceTests.setUp
    tearDown = workspace.WorkspaceTests.tearDown
    base = workspace.WorkspaceTests.base
    upload = workspace.WorkspaceTests.upload

    def fixture(self, text):
        class Chunks(httpx.AsyncByteStream):
            async def __aiter__(self):
                encoded = text.encode()
                for index in range(0, len(encoded), 3):
                    yield encoded[index:index + 3]
        async def handler(request):
            self.requests.append(request)
            return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=Chunks())
        return patch.object(OpenAICompatibleProvider, '_async_client',
            side_effect=lambda config: httpx.AsyncClient(base_url=config.base_url,
                                                         transport=httpx.MockTransport(handler)))

    def events(self, response):
        return [(block.splitlines()[0][7:], json.loads(block.splitlines()[1][6:]))
                for block in response.text.strip().split('\n\n')]

    def test_answer_arrives_in_deltas_and_records_usage_once(self):
        base = self.base()
        self.upload(base)
        upstream = ('data: {"choices":[{"delta":{"content":"中文"}}]}\r\n\r\n'
                    'data: {"choices":[{"delta":{"content":"答案（Chunk 0）"}}]}\n\n'
                    'data: {"choices":[],"usage":{"prompt_tokens":100,"completion_tokens":25,"total_tokens":125}}\n\n'
                    'data: [DONE]\n\n')
        with self.fixture(upstream):
            response = self.client.post('/api/knowledge/ask/stream', json={'question': '发布流程', 'knowledge_base_id': base})
        self.assertEqual(response.status_code, 200, response.text)
        events = self.events(response)
        self.assertEqual([name for name, _ in events], ['meta', 'delta', 'delta', 'done'])
        self.assertEqual(''.join(item['text'] for name, item in events if name == 'delta'), '中文答案（Chunk 0）')
        self.assertGreater(len(events[0][1]['sources']), 0)
        self.assertTrue(json.loads(self.requests[-1].content)['stream'])
        usage = self.client.get('/api/usage', params={'action': 'ask'}).json()
        self.assertEqual(usage['total'], 1)
        self.assertEqual(usage['summary']['total_tokens'], 125)
        self.assertEqual(usage['summary']['failures'], 0)
        self.assertEqual(response.headers['x-accel-buffering'], 'no')

    def test_truncated_stream_retains_partial_usage_and_reports_failure(self):
        base = self.base()
        self.upload(base)
        upstream = ('data: {"choices":[{"delta":{"content":"部分答案"}}]}\n\n'
                    'data: {"usage":{"total_tokens":42}}\n\n')
        with self.fixture(upstream):
            response = self.client.post('/api/knowledge/ask/stream', json={'question': '发布流程', 'knowledge_base_id': base})
        events = self.events(response)
        self.assertEqual(events[-1][0], 'error')
        self.assertNotIn('done', [name for name, _ in events])
        self.assertEqual(events[1][1]['text'], '部分答案')
        usage = self.client.get('/api/usage').json()
        self.assertEqual(usage['total'], 1)
        self.assertEqual(usage['summary']['failures'], 1)
        self.assertEqual(usage['summary']['total_tokens'], 42)

    def test_continuation_reuses_sources_and_accumulated_answer(self):
        base = self.base()
        self.upload(base)
        payload = {'question': '发布流程', 'knowledge_base_id': base}
        with self.fixture('data: {"choices":[{"delta":{"content":"```python\\nprint("}}]}\n\n'):
            initial = self.events(self.client.post('/api/knowledge/ask/stream', json=payload))
        meta = initial[0][1]
        answer = initial[1][1]['text']
        for delta in ['1)', '\n```']:
            payload['continuation'] = {'answer': answer, 'sources': meta['sources'], 'web_sources': meta['web_sources']}
            upstream = 'data: ' + json.dumps({'choices': [{'delta': {'content': delta}}]}) + '\n\ndata: [DONE]\n\n'
            with patch('app.api.routes.knowledge.KnowledgeIngestionRepository.search_chunks', side_effect=AssertionError('must reuse context')):
                with self.fixture(upstream):
                    events = self.events(self.client.post('/api/knowledge/ask/stream', json=payload))
            self.assertEqual(events[0][1]['sources'], meta['sources'])
            self.assertEqual(events[-1][0], 'done')
            sent = json.loads(self.requests[-1].content)['messages']
            self.assertEqual(sent[-2], {'role': 'assistant', 'content': answer})
            self.assertIn('只输出新增内容', sent[-1]['content'])
            answer += ''.join(item['text'] for name, item in events if name == 'delta')
        self.assertEqual(answer, '```python\nprint(1)\n```')
        usage = self.client.get('/api/usage', params={'action': 'ask'}).json()
        self.assertEqual(usage['total'], 3)

    def test_validation_and_mock_usage(self):
        result = self.client.post('/api/knowledge/ask/stream', json={'question': 'test', 'knowledge_base_id': 'missing'})
        self.assertEqual(result.status_code, 404)
        base = self.base()
        self.upload(base)
        response = self.client.post('/api/knowledge/ask/stream', json={'question': '发布流程', 'knowledge_base_id': base, 'provider_id': 'mock'})
        events = self.events(response)
        self.assertEqual(events[-1][0], 'done')
        self.assertEqual(events[-1][1]['usage']['source'], 'mock')
        self.assertIsNone(events[-1][1]['usage']['total_tokens'])

    def test_cancellation_closes_stream_and_logs_partial_answer_once(self):
        base = self.base()
        self.upload(base)
        class Request:
            async def is_disconnected(self): return False
        async def scenario():
            response = await stream_knowledge(AskRequest(question='发布流程', knowledge_base_id=base), Request(), self.db)
            stream = response.body_iterator
            self.assertIn('event: meta', await anext(stream))
            self.assertIn('event: delta', await anext(stream))
            with self.assertRaises(asyncio.CancelledError):
                await stream.athrow(asyncio.CancelledError())
        with self.fixture('data: {"choices":[{"delta":{"content":"部分回答"}}]}\n\ndata: [DONE]\n\n'):
            asyncio.run(scenario())
        logs = AIRepository(self.db).list_activity_logs()
        self.assertEqual(len(logs), 1)
        self.assertFalse(logs[0].success)
        self.assertEqual(logs[0].response_text, '部分回答')
