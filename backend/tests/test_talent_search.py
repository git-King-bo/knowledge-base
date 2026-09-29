import io
import json
import unittest
from unittest.mock import patch

from openpyxl import Workbook

import test_workspace as workspace
import test_streaming as streaming
from app.repositories.sqlite import KnowledgeIngestionRepository
from app.services.talent_search import TalentFilter, TalentPlan, TalentSheet, execute_plan, read_talent_sheets, rule_plan, talent_context


class TalentSearchTests(unittest.TestCase):
    setUp = workspace.WorkspaceTests.setUp
    tearDown = workspace.WorkspaceTests.tearDown
    base = workspace.WorkspaceTests.base
    fixture = streaming.StreamingTests.fixture

    def roster(self, base):
        workbook = Workbook()
        sheet = workbook.active
        # Deliberately reorder fields: values must follow headers, not positions.
        sheet.append(['领域', 'Google Scholar h-index', '姓名', '当前机构', 'OpenAlex h-index'])
        for row in [
            ['具身智能', 999, '甲', '甲大学', '9'],
            ['具身智能', 1, '乙', '甲大学', '100'],
            ['具身智能', 2, '丙', '乙大学', None],
            ['具身智能', 3, '丁', '乙大学', '0'],
            ['量子计算', 4, '戊', '甲大学', '200'],
            ['具身智能', 5, '己', '甲大学', '未知'],
        ]:
            sheet.append(row)
        output = io.BytesIO()
        workbook.save(output)
        workbook.close()
        response = self.client.post(f'/api/knowledge/bases/{base}/upload', files={
            'file': ('人才900.xlsx', output.getvalue(), 'application/octet-stream')})
        self.assertEqual(response.status_code, 201, response.text)
        return KnowledgeIngestionRepository(self.db).list_active_spreadsheet_sources(base)

    def test_domain_sort_uses_full_rows_numeric_order_and_correct_metric(self):
        sources = self.roster(self.base())
        sheets, failures = read_talent_sheets(sources)
        self.assertEqual(failures, [])
        plan = rule_plan('帮我查询具身智能领域 并且按照openlex h-index排名', sheets)
        result = execute_plan(plan, sheets)[0]
        self.assertEqual(result['matched_records'], 5)
        self.assertEqual(result['missing_sort_values'], 2)
        self.assertEqual(result['rankable_records'], 3)
        self.assertEqual([record['fields']['姓名'] for record in result['records']], ['乙', '甲', '丁'])
        self.assertEqual([record['excel_row'] for record in result['records']], [3, 2, 5])
        ascending = execute_plan(TalentPlan(filters=plan.filters, sort_by='OpenAlex h-index', descending=False, limit=1), sheets)[0]
        self.assertEqual(ascending['records'][0]['fields']['姓名'], '丁')
        self.assertTrue(ascending['truncated'])

    def test_natural_language_plan_preserves_compound_filters_and_rejects_fake_columns(self):
        sources = self.roster(self.base())
        sheets, _ = read_talent_sheets(sources)
        question = '帮我找甲大学的具身智能人才，OpenAlex h-index至少10'
        self.assertIsNone(rule_plan(question, sheets))
        plan = TalentPlan(filters=[TalentFilter(field='领域', value='具身智能'),
            TalentFilter(field='当前机构', value='甲大学'), TalentFilter(field='OpenAlex h-index', op='gte', value='10')],
            sort_by='OpenAlex h-index')
        result = json.loads(talent_context(question, sources, lambda schema: plan.model_dump_json()))['results'][0]
        self.assertEqual(result['matched_records'], 1)
        self.assertEqual(result['records'][0]['fields']['姓名'], '乙')
        invalid = TalentPlan(filters=[TalentFilter(field='虚构指标', value='1')])
        self.assertIn('无法可靠确定', talent_context(question, sources, lambda schema: invalid.model_dump_json()))
        self.assertIsNone(rule_plan('具身智能按h-index排名', sheets))

    def test_ask_and_stream_receive_structured_evidence_even_when_retrieval_empty(self):
        base = self.base()
        self.roster(base)
        self.roster(self.base('隔离库'))
        payload = {'question': '具身智能领域按OpenAlex h-index排名', 'knowledge_base_id': base, 'top_k': 1, 'talent_page_size': 1}
        with patch('app.api.routes.knowledge.KnowledgeIngestionRepository.search_chunks', return_value=[]):
            response = self.client.post('/api/knowledge/ask', json=payload)
            self.assertEqual(response.status_code, 200, response.text)
            evidence = response.json()['row_sources']
            self.assertEqual(len(evidence), 1)
            self.assertEqual(evidence[0]['filename'], '人才900.xlsx')
            self.assertEqual(evidence[0]['excel_row'], 3)
            self.assertEqual(evidence[0]['fields']['OpenAlex h-index'], '100')
            self.assertEqual(evidence[0]['index'], 1)
            self.assertIn('其中 3 条有 OpenAlex h-index', response.json()['answer'])
            self.assertNotIn('rankable_records', response.json()['answer'])
            self.assertEqual(response.json()['query_state']['returned'], 1)
            with self.fixture('data: {"choices":[{"delta":{"content":"已按指标排序"}}]}\n\ndata: [DONE]\n\n'):
                response = self.client.post('/api/knowledge/ask/stream', json=payload)
            self.assertIn('event: done', response.text)
            events = [json.loads(block.splitlines()[1][6:]) for block in response.text.strip().split('\n\n')
                      if block.startswith('event: meta')]
            self.assertEqual(events[0]['row_sources'], evidence)
            self.assertIn('另有 2 条缺少该指标', response.text)

    def test_search_returns_structured_rows_and_zero_matches_is_explicit(self):
        base = self.base()
        sources = self.roster(base)
        response = self.client.get('/api/knowledge/search', params={
            'q': '具身智能领域按OpenAlex h-index排名', 'knowledge_base_id': base, 'top_k': 1})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['talent_results'][0]['returned_records'], 1)
        self.assertEqual(response.json()['hits'], [])
        sheets, _ = read_talent_sheets(sources)
        result = execute_plan(TalentPlan(filters=[TalentFilter(field='领域', value='不存在领域')]), sheets)[0]
        self.assertEqual(result['matched_records'], 0)
        self.assertEqual(result['records'], [])

    def test_top_k_caps_rule_and_model_plans_across_files_without_changing_totals(self):
        sheets = [TalentSheet(str(index), f'名单{index}.xlsx', 'Sheet1', ['姓名', '领域', 'OpenAlex h-index'],
            [{'row': i + 2, 'fields': {'姓名': f'人员{index}-{i}', '领域': '具身智能',
                                      'OpenAlex h-index': str(index * 100 + i)}} for i in range(82)])
            for index in range(2)]
        question = '具身智能领域按OpenAlex h-index排名前100'
        with patch('app.services.talent_search.read_talent_sheets', return_value=(sheets, [])):
            context = json.loads(talent_context(question, [], max_results=5))
            self.assertEqual([r['matched_records'] for r in context['results']], [82, 82])
            self.assertEqual(sum(r['returned_records'] for r in context['results']), 5)
            records = [record for result in context['results'] for record in result['records']]
            self.assertEqual([record['fields']['OpenAlex h-index'] for record in records], ['181', '180', '179', '178', '177'])
            plan = TalentPlan(filters=[TalentFilter(field='领域', value='具身智能')], limit=100)
            context = json.loads(talent_context('帮我提取具身智能领域的人才', [],
                lambda schema: plan.model_dump_json(), max_results=5))
            self.assertEqual(sum(r['returned_records'] for r in context['results']), 5)

    def test_aggregate_counts_full_table_and_routes_semantic_queries(self):
        sources = self.roster(self.base())
        for operation in ['distinct_count', 'group_count']:
            raw = json.dumps({'intent': 'aggregate', 'operation': operation, 'field': '领域'})
            result = json.loads(talent_context('此知识库包含了多少领域', sources, lambda schema: raw))['aggregate']
            self.assertEqual(result['distinct'], 2)
            self.assertEqual(result['records'], 6)
            self.assertEqual(result['groups'], {'具身智能': 5, '量子计算': 1})
        self.assertIsNone(talent_context('找与我的项目需求相关的人才', sources,
            lambda schema: '{"intent":"semantic"}'))
        self.assertIsNone(talent_context('解释领域定义', sources,
            lambda schema: '{"intent":"document"}'))
        self.assertEqual(talent_context('计算人才平均指标', sources,
            lambda schema: '{"intent":"unsupported","message":"暂不支持平均值统计"}'), '暂不支持平均值统计')

    def test_aggregate_ask_and_stream_return_program_computed_answer(self):
        base = self.base()
        self.roster(base)
        with patch('app.api.routes.knowledge._talent_query_planner',
                   return_value=lambda schema: '{"intent":"aggregate","operation":"distinct_count","field":"领域"}'):
            payload = {'question': '此知识库包含了多少领域', 'knowledge_base_id': base}
            response = self.client.post('/api/knowledge/ask', json=payload)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIn('共有 2 个', response.json()['answer'])
            response = self.client.post('/api/knowledge/ask/stream', json=payload)
            self.assertIn('共有 2 个', response.text)
            self.assertIn('event: done', response.text)

    def test_fallback_distinguishes_model_failure_ambiguous_metric_and_invalid_plan(self):
        from unittest.mock import Mock
        sources = self.roster(self.base())
        failed = talent_context('查找甲大学人才', sources, Mock(side_effect=RuntimeError('private provider error')))
        self.assertIn('模型调用失败', failed)
        self.assertNotIn('private provider error', failed)
        ambiguous = talent_context('具身智能按h-index排名', sources, lambda schema: '{}')
        self.assertIn('Google Scholar h-index', ambiguous)
        self.assertIn('OpenAlex h-index', ambiguous)
        unknown = talent_context('推荐适合这个项目的人才', sources, lambda schema: '{}')
        self.assertIn('推荐适合这个项目的人才', unknown)
        self.assertIn('不表示知识库没有相关数据', unknown)
        self.assertNotIn('前20名', unknown)

    def test_aggregate_preserves_filters_and_rejects_incomplete_sources(self):
        sources = self.roster(self.base())
        plan = {'intent': 'aggregate', 'operation': 'count',
                'filters': [{'field': '当前机构', 'value': '甲大学'}]}
        result = json.loads(talent_context('甲大学多少人才', sources, lambda schema: json.dumps(plan)))
        self.assertEqual(result['aggregate']['records'], 4)
        plan.update(operation='distinct_count', field='不存在的字段')
        self.assertIn('本次未执行查询', talent_context('有多少不同字段值', sources, lambda schema: json.dumps(plan)))
        sheets, _ = read_talent_sheets(sources)
        plan.update(field='领域')
        with patch('app.services.talent_search.read_talent_sheets', return_value=(sheets, ['损坏.xlsx'])):
            self.assertIn('不能可靠给出全库统计结果', talent_context('有多少领域', sources, lambda schema: json.dumps(plan)))

    def test_planner_contract_shares_runtime_schema_and_aliases(self):
        from app.services.talent_search import query_planner_instructions, normalized
        contract = json.loads(query_planner_instructions().split('\n', 1)[1])
        schema = contract['output_schema']
        self.assertEqual(schema, TalentPlan.model_json_schema())
        self.assertEqual(schema['properties']['limit']['maximum'], 100)
        self.assertEqual(schema['properties']['limit']['default'], 20)
        self.assertEqual(set(schema['properties']['intent']['enum']),
                         {'filter', 'aggregate', 'semantic', 'document', 'clarify', 'unsupported'})
        for alias, canonical in contract['term_aliases'].items():
            self.assertEqual(normalized(alias + ' h-index'), normalized(canonical + ' h-index'))

    def test_management_metric_sort_is_numeric_before_pagination_and_nulls_last(self):
        base = self.base()
        from app.services.talent_import import read_personnel
        from app.db.models import TalentModel
        from pathlib import Path
        sources = self.roster(base)
        for source in sources:
            self.db.add_all([TalentModel(**record, created_at=__import__('datetime').datetime(2026, 9, 29)) for record in read_personnel(Path(source.storage_path), source.id)])
        self.db.commit()
        def names(order, page=1, size=20):
            response = self.client.get('/api/talents', params={'knowledge_base_id': base,
                'sort_by': 'openalex_h_index', 'sort_order': order, 'page': page, 'page_size': size})
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()['items']
        descending = names('desc')
        self.assertEqual([row['name'] for row in descending[:4]], ['戊', '乙', '甲', '丁'])
        self.assertEqual(descending[0]['openalex_h_index'], '200')
        self.assertEqual([row['name'] for row in names('asc')[:4]], ['丁', '甲', '乙', '戊'])
        self.assertEqual(names('desc', 2, 1)[0]['name'], '乙')
        response = self.client.get('/api/talents', params={'knowledge_base_id': base,
            'organization': '乙大学', 'sort_by': 'openalex_h_index', 'sort_order': 'desc'})
        self.assertEqual([row['name'] for row in response.json()['items']], ['丁', '丙'])
