"""Business invariants across corpus size, phrasing, budgets and query pages."""
import json
import unittest
from unittest.mock import Mock, patch

from app.core.security import usage_counter
from app.services.talent_search import TalentPlan, TalentConcept, TalentSheet, talent_context
from app.services.talent_results import load_result


def corpus(size=61):
    return TalentSheet('source', 'people.xlsx', 'Sheet1', ['姓名','当前机构','研究方向','OpenAlex h-index','创业／项目经历'], [
        {'row': i+2, 'fields': {'姓名': f'人员{i}', '当前机构': 'Example University',
          '研究方向': '控制系统', 'OpenAlex h-index': str(i),
          '创业／项目经历': '创办技术公司' if i % 3 == 0 else '产业研究'}} for i in range(size)])


class TalentExecutionTests(unittest.TestCase):
    def run_query(self, data, plan, *, previous=None, size=5, predicate=lambda row: True, spent=1):
        counter = {'dispatched': spent}
        token = usage_counter.set(counter)
        calls = []
        def planner(payload):
            if payload.get('phase') != 'verify_candidates':
                return plan.model_dump_json()
            counter['dispatched'] += 1
            self.assertLessEqual(counter['dispatched'], 4)
            calls.append(len(payload['candidates']))
            return json.dumps({'decisions': [{'id': r['id'], 'checks': [
                {'status': 'supported' if predicate(r) else 'contradicted', 'refs': [0]}
                for _ in payload['conditions']]} for r in payload['candidates']]})
        kwargs = dict(snapshot_scope=('test-user', 'base', 'revision'), max_results=size)
        if previous:
            kwargs.update(snapshot_id=previous['snapshot_id'], saved_plan=TalentPlan.model_validate(previous['plan']),
                          offset=previous['pagination']['offset'] + previous['pagination']['returned'])
        try:
            with patch('app.services.talent_search.read_talent_sheets', return_value=([data], [])):
                result = json.loads(talent_context('按条件查找人才', [], planner, **kwargs))
            return result, calls
        finally:
            usage_counter.reset(token)

    def test_budget_boundaries_preserve_progress_and_never_abort_by_population(self):
        for size in (12,13,18,19,61,1001):
            for spent in (1,2):
                with self.subTest(size=size, spent=spent):
                    result, calls = self.run_query(corpus(size), TalentPlan(evidence_conditions=['符合任职条件']), spent=spent)
                    self.assertEqual(result['coverage']['evaluated'], min(size, 6))
                    self.assertEqual(result['matched'], result['coverage']['evaluated'])
                    self.assertLessEqual(len(calls), 4-spent)
                    self.assertNotIn('_execution', result)

    def test_all_pages_are_complete_unique_and_resume_without_replanning(self):
        data = corpus()
        plan = TalentPlan(evidence_conditions=['符合任职条件'])
        result = None
        seen = []
        total_calls = 0
        for _ in range(20):
            result, calls = self.run_query(data, plan, previous=result)
            total_calls += len(calls)
            seen += [r['excel_row'] for g in result['results'] for r in g['records']]
            if not result['pagination']['has_more']:
                break
        self.assertEqual(seen, list(range(2,63)))
        self.assertTrue(result['coverage']['complete'])
        self.assertEqual(total_calls, 11)

    def test_empty_first_window_can_continue_and_find_late_match(self):
        data = corpus(40)
        plan = TalentPlan(evidence_conditions=['符合任职条件'])
        predicate = lambda row: row['fields']['姓名'] == '人员39'
        result, _ = self.run_query(data, plan, predicate=predicate)
        self.assertEqual(result['matched'], 0)
        self.assertTrue(result['pagination']['has_more'])
        for _ in range(3):
            if result['matched']:
                break
            result, _ = self.run_query(data, plan, previous=result, predicate=predicate)
        self.assertEqual(result['matched'], 1)
        self.assertEqual(result['results'][0]['records'][0]['fields']['姓名'], '人员39')

    def test_ranking_prioritizes_global_metric_not_recall_position(self):
        data = corpus(1001)
        plan = TalentPlan(sort_by='OpenAlex h-index', result_limit=3,
                          evidence_conditions=['符合研究条件'],
                          concepts=[TalentConcept(fields=['研究方向'], terms=['任意同义表达'])])
        result, _ = self.run_query(data, plan, size=2)
        self.assertEqual([r['fields']['OpenAlex h-index'] for g in result['results'] for r in g['records']], ['1000','999'])
        self.assertTrue(result['coverage']['ranking_proven'])
        result, calls = self.run_query(data, plan, previous=result, size=2)
        self.assertEqual(calls, [])
        self.assertEqual([r['fields']['OpenAlex h-index'] for g in result['results'] for r in g['records']], ['998'])
        self.assertFalse(result['pagination']['has_more'])

    def test_explicit_total_limit_and_page_size_are_independent(self):
        plan = TalentPlan(sort_by='OpenAlex h-index', result_limit=3)
        result, _ = self.run_query(corpus(35), plan, size=5)
        self.assertEqual(result['pagination']['returned'], 3)
        self.assertFalse(result['pagination']['has_more'])
        result, _ = self.run_query(corpus(35), TalentPlan(sort_by='OpenAlex h-index'), size=100)
        self.assertEqual(result['pagination']['returned'], 35)

    def test_missing_metrics_remain_visible_across_pages_in_both_directions(self):
        for descending in (True, False):
            data = corpus(5)
            for index in (1, 3):
                data.rows[index]['fields']['OpenAlex h-index'] = ''
            plan = TalentPlan(sort_by='OpenAlex h-index', descending=descending)
            result = None
            seen = []
            while True:
                result, _ = self.run_query(data, plan, previous=result, size=2)
                seen.extend(r['fields']['姓名'] for g in result['results'] for r in g['records'])
                if not result['pagination']['has_more']:
                    break
            numeric = ['人员4', '人员2', '人员0'] if descending else ['人员0', '人员2', '人员4']
            self.assertEqual(seen, numeric + ['人员1', '人员3'])
            self.assertEqual(result['missing'], 2)

    def test_resort_preserves_missing_records_and_their_previous_order(self):
        from app.services.talent_results import sort_result
        evidence = {'results': [{'source_id':'s','sheet':'t','records':[
            {'excel_row':i,'fields':{'score':value}} for i,value in [(1,''),(2,'0'),(3,''),(4,'5')]]}],
            'result_order':[['s','t',3],['s','t',4],['s','t',1],['s','t',2]], 'plan':{}}
        result = json.loads(sort_result(evidence, 'score', True, None, 'sort', 10))
        self.assertEqual([k[2] for k in result['result_order']], [4,2,3,1])

    def test_missing_evidence_cannot_certify_global_ranking(self):
        data = corpus(10)
        plan = TalentPlan(sort_by='OpenAlex h-index', evidence_conditions=['符合任职条件'])
        def planner(payload):
            return json.dumps({'decisions': [{'id': r['id'], 'checks': [{
                'status': 'unknown' if r['fields']['姓名'] == '人员9' else 'supported', 'refs': [0]}]}
                for r in payload['candidates']]})
        with patch('app.services.talent_search.read_talent_sheets', return_value=([data], [])):
            result = json.loads(talent_context('排序', [], planner, saved_plan=plan))
        self.assertFalse(result['coverage']['ranking_proven'])
        self.assertEqual(result['ranking_scope'], 'matched_results')

    def test_snapshot_scope_and_revision_are_checked_before_continuing(self):
        result, _ = self.run_query(corpus(30), TalentPlan(evidence_conditions=['符合任职条件']))
        for scope in [('other-user','base','revision'), ('test-user','other-base','revision'), ('test-user','base','new-revision')]:
            self.assertIsNone(load_result(result['snapshot_id'], scope, '按条件查找人才', result['plan']))
        planner = Mock(side_effect=AssertionError('Must not call a model'))
        notice = talent_context('按条件查找人才', [], planner, snapshot_scope=scope,
            saved_plan=TalentPlan.model_validate(result['plan']), snapshot_id=result['snapshot_id'])
        self.assertIn('已过期', notice)

    def test_all_business_fields_reach_verifier(self):
        observed = []
        def planner(payload):
            observed.extend(payload['candidates'])
            return json.dumps({'decisions': [{'id': r['id'], 'checks': [{'status':'unknown','refs':[]}]}
                                           for r in payload['candidates']]})
        with patch('app.services.talent_search.read_talent_sheets', return_value=([corpus(1)], [])):
            talent_context('有创业经历的人才', [], planner, saved_plan=TalentPlan(evidence_conditions=['有创业经历']))
        self.assertIn('创业／项目经历', observed[0]['fields'])

    def test_semantic_statistics_are_partial_until_full_scope_is_evaluated(self):
        from app.services.talent_answer import render_aggregate_answer
        plan=TalentPlan(intent='aggregate', operation='count', evidence_conditions=['有创业经历'])
        data=corpus(40)
        predicate=lambda row: row['fields']['创业／项目经历']=='创办技术公司'
        result, _=self.run_query(data,plan,predicate=predicate)
        self.assertEqual(result['aggregate']['records'],6)
        self.assertIn('不能视为全库精确总数',render_aggregate_answer(result))
        self.assertEqual(result['pagination']['returned'],0)
        while result['pagination']['has_more']:
            result, _=self.run_query(data,plan,previous=result,predicate=predicate)
        self.assertEqual(result['aggregate']['records'],14)
        self.assertTrue(result['coverage']['complete'])
        self.assertNotIn('不能视为全库精确总数',render_aggregate_answer(result))


if __name__ == '__main__':
    unittest.main()
