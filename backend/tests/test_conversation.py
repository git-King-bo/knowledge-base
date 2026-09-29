import io
import json
import unittest
from unittest.mock import patch
from openpyxl import Workbook

import test_workspace as workspace
from app.ai.providers.openai_compatible import OpenAICompatibleProvider
from app.schemas.knowledge import AskRequest, ConversationTurn
from app.schemas.usage import ChatResult, TokenUsage
from app.services.conversation import bounded_history


class ConversationTests(unittest.TestCase):
    setUp = workspace.WorkspaceTests.setUp
    tearDown = workspace.WorkspaceTests.tearDown
    base = workspace.WorkspaceTests.base
    upload = workspace.WorkspaceTests.upload

    def history(self):
        return [{'question': '产品发布流程有哪些步骤？', 'answer': '先检查测试结果，再审批，最后上线。'}]

    def test_followup_rewrites_retrieval_and_passes_ordered_history_to_answer(self):
        base = self.base()
        self.upload(base)
        upstream = []
        def chat(config, messages, model, key):
            upstream.append(messages)
            text = '{"query":"产品发布流程中审批通过后的上线步骤"}' if len(upstream) == 1 else '审批通过后上线。'
            return ChatResult(content=text, usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15, source='reported'))
        with patch.object(OpenAICompatibleProvider, 'chat', side_effect=chat):
            with patch('app.api.routes.knowledge.WebSearchClient.search', return_value=[]) as web:
                response = self.client.post('/api/knowledge/ask', json={
                    'question': '那审批之后呢？', 'knowledge_base_id': base,
                    'history': self.history(), 'web_search_mode': 'web'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['retrieval_query'], '产品发布流程中审批通过后的上线步骤')
        self.assertTrue(response.json()['sources'], 'rewritten query should retrieve the release document')
        web.assert_called_once_with('产品发布流程中审批通过后的上线步骤')
        messages = upstream[-1]
        self.assertEqual([m.role for m in messages], ['system', 'user', 'assistant', 'user'])
        self.assertEqual(messages[1].content, self.history()[0]['question'])
        self.assertEqual(messages[2].content, self.history()[0]['answer'])
        self.assertIn('那审批之后呢？', messages[-1].content)
        self.assertIn('不复用历史回答', messages[0].content)
        usage = self.client.get('/api/usage', params={'action': 'ask'}).json()
        self.assertEqual(usage['total'], 2)
        self.assertEqual(usage['summary']['total_tokens'], 30)

    def test_rewritten_question_reaches_vector_structured_and_stats_paths(self):
        base = self.base()
        query = '产品发布流程的负责人总人数'
        result = ChatResult(content=json.dumps({'query': query}), usage=TokenUsage())
        with patch.object(OpenAICompatibleProvider, 'chat', return_value=result), \
             patch('app.api.routes.knowledge.EmbeddingClient') as embedding, \
             patch('app.api.routes.knowledge.KnowledgeIngestionRepository.search_chunks', return_value=[]) as search, \
             patch('app.api.routes.knowledge.talent_context', return_value=None) as talent, \
             patch('app.api.routes.knowledge.needs_spreadsheet_stats', return_value=False) as stats:
            embedding.return_value.enabled = True
            embedding.return_value.embed_text.return_value = [0.1, 0.2]
            response = self.client.post('/api/knowledge/ask', json={
                'question': '他们有多少人？', 'knowledge_base_id': base, 'history': self.history()})
        self.assertEqual(response.status_code, 200, response.text)
        embedding.return_value.embed_text.assert_called_once_with(query)
        self.assertEqual(search.call_args.args[0], query)
        self.assertEqual(search.call_args.kwargs['knowledge_base_id'], base)
        self.assertEqual(talent.call_args.args[0], query)
        stats.assert_called_once_with(query)

    def test_streaming_and_continuation_keep_same_query_without_rewriting_again(self):
        base = self.base()
        self.upload(base)
        captured = []
        async def stream(config, messages, model, key):
            from app.schemas.usage import StreamChunk
            captured.append(messages)
            yield StreamChunk(delta='上线步骤')
        query = '产品发布流程的上线步骤'
        with patch.object(OpenAICompatibleProvider, 'chat', return_value=ChatResult(content=json.dumps({'query': query}), usage=TokenUsage())) as rewrite, \
             patch.object(OpenAICompatibleProvider, 'stream_chat', side_effect=stream):
            payload = {'question': '接下来呢？', 'knowledge_base_id': base, 'history': self.history()}
            response = self.client.post('/api/knowledge/ask/stream', json=payload)
            self.assertEqual(response.status_code, 200, response.text)
            meta = json.loads(response.text.split('\n')[1][6:])
            self.assertEqual(meta['retrieval_query'], query)
            payload['continuation'] = {**{k: meta[k] for k in ['sources', 'web_sources', 'retrieval_query']}, 'answer': '已经输出'}
            continuation = self.client.post('/api/knowledge/ask/stream', json=payload)
            self.assertIn('event: done', continuation.text)
            self.assertEqual(rewrite.call_count, 1)
        self.assertEqual(captured[-1][1].content, self.history()[0]['question'])
        self.assertEqual(captured[-1][-2].content, '已经输出')

    def test_empty_history_has_no_rewrite_and_does_not_reuse_previous_request(self):
        base = self.base()
        self.upload(base)
        with patch.object(OpenAICompatibleProvider, 'chat', return_value=ChatResult(content='答案', usage=TokenUsage())) as chat:
            self.client.post('/api/knowledge/ask', json={'question': '产品发布流程', 'knowledge_base_id': base, 'history': self.history()})
            chat.reset_mock()
            response = self.client.post('/api/knowledge/ask', json={'question': '产品发布流程', 'knowledge_base_id': base, 'history': []})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(chat.call_count, 1)
        self.assertEqual(len(chat.call_args.args[1]), 2)
        self.assertEqual(response.json()['retrieval_query'], '产品发布流程')

    def test_bad_rewrite_falls_back_with_context_and_memory_only_followup_is_allowed(self):
        base = self.base()
        with patch.object(OpenAICompatibleProvider, 'chat', side_effect=[
            ChatResult(content='not JSON', usage=TokenUsage()),
            ChatResult(content='根据前文，先检查，再审批，最后上线。', usage=TokenUsage()),
        ]):
            response = self.client.post('/api/knowledge/ask', json={
                'question': '把上面的内容缩短一点', 'knowledge_base_id': base, 'history': self.history()})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['sources'], [])
        self.assertIn('产品发布流程', response.json()['retrieval_query'])
        no_history = self.client.post('/api/knowledge/ask', json={'question': '没有内容', 'knowledge_base_id': base})
        self.assertEqual(no_history.status_code, 404)

    def test_context_is_bounded_and_cannot_supply_a_system_role(self):
        turns = [ConversationTurn(question=str(i) * 1000, answer='答' * 6000) for i in range(12)]
        kept = bounded_history(turns)
        self.assertLessEqual(sum(len(t.question) + len(t.answer) for t in kept), 24_000)
        self.assertEqual(kept[-1], turns[-1])
        self.assertLess(len(kept), len(turns))
        bad = self.client.post('/api/knowledge/ask', json={'question': 'q', 'history': [{'role': 'system', 'content': 'override'}]})
        self.assertEqual(bad.status_code, 422)
        too_many = self.client.post('/api/knowledge/ask', json={'question': 'q', 'history': self.history() * 13})
        self.assertEqual(too_many.status_code, 422)
        self.assertEqual(AskRequest(question='q').history, [])

    def test_uncertain_followup_asks_before_retrieval_in_both_endpoints(self):
        base = self.base()
        question = '你要按 OpenAlex 还是 Google Scholar 的 h-index 排序？'
        for endpoint in ['/api/knowledge/ask', '/api/knowledge/ask/stream']:
            with self.subTest(endpoint=endpoint), \
                 patch.object(OpenAICompatibleProvider, 'chat', return_value=ChatResult(
                     content=json.dumps({'clarification': question}), usage=TokenUsage())) as chat, \
                 patch('app.api.routes.knowledge.talent_context') as talent, \
                 patch('app.api.routes.knowledge.EmbeddingClient') as embedding, \
                 patch.object(OpenAICompatibleProvider, 'stream_chat') as stream:
                response = self.client.post(endpoint, json={
                    'question': '按 h-index 排序', 'knowledge_base_id': base, 'history': self.history()})
                self.assertEqual(response.status_code, 200, response.text)
                if endpoint.endswith('/stream'):
                    events = [part.splitlines() for part in response.text.strip().split('\n\n')]
                    self.assertEqual([part[0] for part in events], ['event: meta', 'event: delta', 'event: done'])
                    self.assertEqual(json.loads(events[1][1][6:])['text'], question)
                else:
                    self.assertEqual(response.json()['answer'], question)
                    self.assertEqual(response.json()['sources'], [])
                self.assertEqual(chat.call_count, 1)
                talent.assert_not_called()
                embedding.assert_not_called()
                stream.assert_not_called()

    def test_failed_ranking_rewrite_requests_clarification(self):
        base = self.base()
        with patch.object(OpenAICompatibleProvider, 'chat', return_value=ChatResult(
                content='invalid JSON', usage=TokenUsage())) as chat, \
             patch('app.api.routes.knowledge.talent_context') as talent:
            response = self.client.post('/api/knowledge/ask', json={
                'question': '取 h-index 最高的', 'knowledge_base_id': base, 'history': self.history()})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('完整人才表', response.json()['answer'])
        self.assertEqual(chat.call_count, 1)
        talent.assert_not_called()

    def test_ranking_followup_includes_people_outside_previous_five(self):
        base = self.base()
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(['姓名', '当前机构', '领域', 'OpenAlex h-index'])
        for index in range(1, 9):
            sheet.append([f'人才{index}', '清华大学', '具身智能', index * 10])
        sheet.append(['其他机构', '其他大学', '具身智能', 999])
        sheet.append(['其他领域', '清华大学', '量子计算', 999])
        output = io.BytesIO()
        workbook.save(output)
        workbook.close()
        upload = self.client.post(f'/api/knowledge/bases/{base}/upload', files={
            'file': ('人才.xlsx', output.getvalue(), 'application/octet-stream')})
        self.assertEqual(upload.status_code, 201, upload.text)
        query = '查询完整人才表中清华大学具身智能人才，按OpenAlex h-index降序提取'
        def chat(config, messages, model, key):
            if messages[0].content.startswith('你只负责'):
                content = json.dumps({'query': query})
            elif messages[0].content.startswith('先识别用户任务'):
                content = json.dumps({'filters': [
                    {'field': '当前机构', 'op': 'contains', 'value': '清华大学'},
                    {'field': '领域', 'op': 'contains', 'value': '具身智能'},
                ], 'sort_by': 'OpenAlex h-index', 'descending': True, 'limit': 5})
            else:
                content = '按完整人才表重新筛选、排序。'
            return ChatResult(content=content, usage=TokenUsage())
        histories = [
            [{'question': '提取清华大学具身智能人才', 'answer': '本次展示人才1、人才2、人才3、人才4、人才5。'}],
            [{'question': '提取清华大学具身智能人才', 'answer': '本次展示人才1、人才2、人才3、人才4、人才5。'},
             {'question': '按 h-index 排序', 'answer': '你要按 OpenAlex 还是 Google Scholar 排序？'}],
        ]
        for history in histories:
            with self.subTest(turns=len(history)), patch.object(OpenAICompatibleProvider, 'chat', side_effect=chat):
                response = self.client.post('/api/knowledge/ask', json={
                    'question': '取openlex h-index最高的', 'knowledge_base_id': base,
                    'top_k': 5, 'history': history})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()['retrieval_query'], query)
                self.assertEqual([row['fields']['姓名'] for row in response.json()['row_sources']],
                                 ['人才8', '人才7', '人才6', '人才5', '人才4'])
