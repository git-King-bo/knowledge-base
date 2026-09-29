import json
import unittest
from unittest.mock import patch
import test_workspace as workspace
import test_streaming as streaming
import test_production as production
from app.db.models import BaseAccessModel
from app.services.agent_trace import capture_trace, trace_output, current_trace
from app.schemas.knowledge import AskRequest
import asyncio


class AgentMonitorTests(unittest.TestCase):
    setUp = workspace.WorkspaceTests.setUp
    tearDown = workspace.WorkspaceTests.tearDown
    base = workspace.WorkspaceTests.base
    upload = workspace.WorkspaceTests.upload
    fixture = streaming.StreamingTests.fixture

    def traces(self, conversation='conversation-a'):
        response = self.client.get('/api/agent-monitor', params={'conversation_id': conversation})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_sync_trace_links_history_and_includes_actual_model_input_and_usage(self):
        base = self.base(); self.upload(base)
        for conversation in ['conversation-a', 'conversation-b']:
            result = self.client.post('/api/knowledge/ask', json={'question': '产品发布流程',
                'knowledge_base_id': base, 'conversation_id': conversation, 'turn_id': 'turn-1'})
            self.assertEqual(result.status_code, 200, result.text)
        result = self.traces()
        self.assertEqual(result['total'], 1)
        row = result['items'][0]
        self.assertEqual(row['status'], 'success')
        self.assertEqual(row['total_tokens'], 125)
        self.assertEqual(row['cached_tokens'], 40)
        self.assertEqual(row['call_count'], 1)
        detail = self.client.get('/api/agent-monitor/' + row['id']).json()
        self.assertEqual(detail['answer'], '知识库测试答案')
        self.assertIsNotNone(detail['first_token_ms'])
        self.assertEqual(detail['turn_id'], 'turn-1')
        self.assertEqual(json.loads(detail['calls'][0]['request_text'])[0]['role'], 'system')
        self.assertIn('知识库检索', [s['name'] for s in detail['stages']])
        self.assertIn('请求结束', [s['name'] for s in detail['stages']])
        self.assertEqual(self.traces('old-history')['total'], 0)
        self.assertEqual(len(self.client.get('/api/agent-monitor/conversations').json()), 2)

    def test_stream_success_and_partial_failure_are_finalized_with_known_usage(self):
        base = self.base(); self.upload(base)
        for final, expected in [('data: [DONE]\n\n', 'success'), ('', 'error')]:
            upstream = ('data: {"choices":[{"delta":{"content":"部分回答"}}]}\n\n'
                        'data: {"usage":{"total_tokens":42}}\n\n' + final)
            with self.fixture(upstream):
                result = self.client.post('/api/knowledge/ask/stream', json={'question': '发布流程',
                    'knowledge_base_id': base, 'conversation_id': 'conversation-a', 'turn_id': 'same-turn'})
            self.assertEqual(result.status_code, 200, result.text)
            row = self.traces()['items'][0]
            self.assertEqual(row['status'], expected)
            self.assertEqual(row['total_tokens'], 42)
            self.assertIsNone(row['input_tokens'])
            detail = self.client.get('/api/agent-monitor/' + row['id']).json()
            self.assertEqual(detail['answer'], '部分回答')
            self.assertEqual(bool(detail['error']), expected == 'error')
        self.assertEqual(self.traces()['total'], 2)

    def test_unknown_usage_and_preparation_failure(self):
        base = self.base(); self.upload(base)
        with self.fixture('data: {"choices":[{"delta":{"content":"答案"}}]}\n\ndata: [DONE]\n\n'):
            self.client.post('/api/knowledge/ask/stream', json={'question': '发布流程',
                'knowledge_base_id': base, 'conversation_id': 'conversation-a'})
        row = self.traces()['items'][0]
        self.assertEqual(row['unknown_calls'], 1)
        self.assertEqual(row['total_tokens'], 0)
        self.assertIsNone(row['output_tokens'])
        result = self.client.post('/api/knowledge/ask', json={'question': '发布流程',
            'knowledge_base_id': base, 'provider_id': 'missing', 'conversation_id': 'conversation-a'})
        self.assertEqual(result.status_code, 404)
        self.assertEqual(self.traces()['items'][0]['status'], 'error')

    def test_cancelled_dependency_preserves_partial_answer_and_releases_context(self):
        async def execute():
            scope = capture_trace(AskRequest(question='中途停止', conversation_id='conversation-a'), self.db)
            await anext(scope)
            trace_output('已生成部分', append=True)
            with self.assertRaises(asyncio.CancelledError):
                await scope.athrow(asyncio.CancelledError())
            self.assertIsNone(current_trace.get())
        asyncio.run(execute())
        row = self.traces()['items'][0]
        self.assertEqual(row['status'], 'cancelled')
        self.assertEqual(self.client.get('/api/agent-monitor/' + row['id']).json()['answer'], '已生成部分')

    def test_vector_retrieval_records_inputs_dimensions_scores_and_skipped_reranking(self):
        from app.core.config import settings
        from app.services.embeddings import EmbeddingClient
        from app.repositories.sqlite import KnowledgeIngestionRepository
        from app.schemas.usage import TokenUsage
        base = self.base()
        source = self.upload(base).json()['source']['id']
        repo = KnowledgeIngestionRepository(self.db)
        repo.replace_chunk_embeddings([(chunk.id, [1.0, 0.0]) for chunk in repo.list_chunks(source)], embedding_model='fixture-embedding')
        with patch.object(settings, 'embedding_api_url', 'https://fixture.invalid'), patch.object(settings, 'embedding_model', 'fixture-embedding'), patch.object(EmbeddingClient, '_embed_texts', return_value=([[1.0, 0.0]], TokenUsage(input_tokens=4, output_tokens=0, total_tokens=4, source='reported'))):
            result = self.client.post('/api/knowledge/ask', json={'question': '产品发布流程', 'knowledge_base_id': base, 'conversation_id': 'conversation-a'})
        self.assertEqual(result.status_code, 200, result.text)
        row = self.traces()['items'][0]
        self.assertEqual(row['total_tokens'], 129)
        detail = self.client.get('/api/agent-monitor/' + row['id']).json()
        stages = {step['name']: step for step in detail['stages']}
        self.assertEqual(stages['向量编码结果']['data']['dimensions'], 2)
        self.assertEqual(stages['独立精排模型']['status'], 'skipped')
        scores = stages['召回与排序结果']['data']['scores']
        self.assertTrue(scores)
        self.assertAlmostEqual(scores[0]['embedding_score'], 1.0)
        call = next(call for call in detail['calls'] if call['action'] == 'embedding')
        self.assertEqual(json.loads(call['request_text'])['input'], ['产品发布流程'])
        self.assertEqual(json.loads(call['response_text'])['vectors'], [[1.0, 0.0]])

    def test_stream_trace_header_and_browser_events_roundtrip(self):
        base = self.base(); self.upload(base)
        with self.fixture('data: {"choices":[{"delta":{"content":"答案"}}]}\n\ndata: [DONE]\n\n'):
            result = self.client.post('/api/knowledge/ask/stream', json={'question': '发布流程', 'knowledge_base_id': base,
                'client_started_at': '2026-09-29T00:00:00Z'})
        trace_id = result.headers['X-Agent-Trace-ID']
        events = [{'name': '页面发起请求', 'elapsed_ms': 0}, {'name': '页面渲染完成', 'elapsed_ms': 300}]
        response = self.client.put('/api/agent-monitor/' + trace_id + '/client-events', json={'events': events})
        self.assertEqual(response.status_code, 200, response.text)
        detail = self.client.get('/api/agent-monitor/' + trace_id).json()
        self.assertEqual(detail['request']['client_events'], events)
        self.assertEqual(detail['answer'], '答案')
        self.assertTrue(detail['stages'])
        self.assertEqual(self.client.put('/api/agent-monitor/' + trace_id + '/client-events', json={'events': [{'name': '非法步骤', 'elapsed_ms': -1}]}).status_code, 422)


class AgentMonitorAccessTests(unittest.TestCase):
    setUp = production.ProductionTests.setUp
    tearDown = production.ProductionTests.tearDown
    login = production.ProductionTests.login
    base = workspace.WorkspaceTests.base
    upload = workspace.WorkspaceTests.upload

    def test_other_users_and_revoked_bases_cannot_read_trace_payload(self):
        self.login('admin'); self.upload(self.base_id)
        self.login('editor')
        self.client.put('/api/conversations/editor-chat', json={'title': '我的历史', 'messages': []})
        result = self.client.post('/api/knowledge/ask', json={'question': '发布流程',
            'knowledge_base_id': self.base_id, 'conversation_id': 'editor-chat'})
        self.assertEqual(result.status_code, 200, result.text)
        row = self.client.get('/api/agent-monitor').json()['items'][0]
        trace_id = row['id']
        self.login('viewer')
        self.assertEqual(self.client.get('/api/agent-monitor').json()['total'], 0)
        self.assertEqual(self.client.get('/api/agent-monitor/' + trace_id).status_code, 404)
        self.assertEqual(self.client.post('/api/knowledge/ask', json={'question': '发布流程',
            'knowledge_base_id': self.base_id, 'conversation_id': 'editor-chat'}).status_code, 404)
        self.login('editor')
        self.db.query(BaseAccessModel).filter_by(user_id='editor').delete(); self.db.commit()
        self.assertEqual(self.client.get('/api/agent-monitor').json()['total'], 0)
        self.assertEqual(self.client.get('/api/agent-monitor/' + trace_id).status_code, 404)

    def test_viewer_can_report_own_browser_timings_but_not_another_users(self):
        self.login('admin'); self.upload(self.base_id)
        self.login('viewer')
        response = self.client.post('/api/knowledge/ask', json={'question': '发布流程', 'knowledge_base_id': self.base_id})
        self.assertEqual(response.status_code, 200, response.text)
        trace_id = self.client.get('/api/agent-monitor').json()['items'][0]['id']
        url = '/api/agent-monitor/' + trace_id + '/client-events'
        payload = {'events': [{'name': '页面渲染完成', 'elapsed_ms': 300}]}
        self.assertEqual(self.client.put(url, json=payload).status_code, 200)
        self.login('editor')
        self.assertEqual(self.client.put(url, json=payload).status_code, 404)


class AgentTalentTraceTests(unittest.TestCase):
    setUp = workspace.WorkspaceTests.setUp
    tearDown = workspace.WorkspaceTests.tearDown
    base = workspace.WorkspaceTests.base

    def test_deterministic_pagination_does_not_invent_model_tokens(self):
        from test_talent_conversation import TalentConversationTests
        from app.ai.providers.openai_compatible import OpenAICompatibleProvider
        base = TalentConversationTests.roster(self)
        with patch.object(OpenAICompatibleProvider, 'chat', side_effect=lambda *args: TalentConversationTests.chat(self, *args)):
            first = self.client.post('/api/knowledge/ask', json={'question': '提取清华大学相关人才',
                'knowledge_base_id': base, 'conversation_id': 'talents', 'turn_id': '1'})
            self.assertEqual(first.status_code, 200, first.text)
            response = first.json()
            second = self.client.post('/api/knowledge/ask', json={'question': '继续',
                'knowledge_base_id': base, 'conversation_id': 'talents', 'turn_id': '2',
                'history': [{'question': '提取清华大学相关人才', 'answer': response['answer'], 'query_state': response['query_state']}]})
            self.assertEqual(second.status_code, 200, second.text)
        monitor = self.client.get('/api/agent-monitor', params={'conversation_id': 'talents', 'page_size': 1}).json()
        self.assertEqual(monitor['total'], 2)
        self.assertEqual(monitor['summary']['call_count'], 1)
        self.assertEqual(monitor['summary']['unknown_calls'], 1)
        self.assertEqual(monitor['items'][0]['call_count'], 0)
        self.assertEqual(monitor['items'][0]['unknown_calls'], 0)
        detail = self.client.get('/api/agent-monitor/' + monitor['items'][0]['id']).json()
        self.assertIn('结构化结果生成', [item['name'] for item in detail['stages']])

    def test_failed_planner_keeps_unknown_call_in_trace(self):
        from test_talent_conversation import TalentConversationTests
        from app.ai.providers.openai_compatible import OpenAICompatibleProvider
        base = TalentConversationTests.roster(self)
        with patch.object(OpenAICompatibleProvider, 'chat', side_effect=RuntimeError('upstream failed')):
            self.client.post('/api/knowledge/ask', json={'question': '提取清华大学相关人才',
                'knowledge_base_id': base, 'conversation_id': 'talents'})
        row = self.client.get('/api/agent-monitor').json()['items'][0]
        self.assertEqual(row['call_count'], 1)
        self.assertEqual(row['unknown_calls'], 1)
        detail = self.client.get('/api/agent-monitor/' + row['id']).json()
        self.assertFalse(detail['calls'][0]['success'])
