import json
import unittest
from unittest.mock import patch
from app.services.talent_search import TalentConcept,TalentPlan,TalentSheet,execute_plan,talent_context
from app.services.talent_evidence import verify_candidates

class TalentEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.fields=['姓名','当前机构','详细个人简介','代表成果','教育经历','细分关键词','OpenAlex h-index']
        self.rows=[{'row':2,'fields':{'姓名':'研究员甲','当前机构':'海外大学','详细个人简介':'从事球形托卡马克和等离子体物理研究','细分关键词':'核聚变','教育经历':'悉尼大学物理学博士','OpenAlex h-index':''}},
                   {'row':3,'fields':{'姓名':'经理乙','当前机构':'聚变投资公司','详细个人简介':'负责财务投资','代表成果':'投资托卡马克装置','细分关键词':'金融','教育经历':'悉尼大学金融学博士','OpenAlex h-index':'99'}}]
        self.sheet=TalentSheet('source','人员.xlsx','Sheet1',self.fields,self.rows)
        self.plan=TalentPlan(concepts=[TalentConcept(fields=['详细个人简介','代表成果','细分关键词'],terms=['托卡马克','tokamak'])],evidence_conditions=['研究托卡马克等离子体物理','具有海外教育经历'])

    def decisions(self,payload):
        result=[]
        for row in payload['candidates']:
            research=row['fields']['姓名']=='研究员甲'
            result.append({'id':row['id'],'conditions':[
                {'condition':0,'status':'supported' if research else 'unknown','evidence':[{'field':'详细个人简介','quote':'从事球形托卡马克和等离子体物理研究'}] if research else []},
                {'condition':1,'status':'supported','evidence':[{'field':'教育经历','quote':row['fields']['教育经历']}]}]})
        return json.dumps({'decisions':result},ensure_ascii=False)

    def test_cross_field_recall_preserves_full_row_and_english_alias(self):
        result=execute_plan(self.plan,[self.sheet],all_records=True)
        self.assertEqual(result[0]['matched_records'],2)
        self.assertEqual(result[0]['records'][0]['fields']['教育经历'],'悉尼大学物理学博士')
        self.rows[0]['fields']['详细个人简介']='Research on tokamak plasma physics'
        self.assertEqual(execute_plan(self.plan,[self.sheet])[0]['matched_records'],2)

    def test_conditions_verified_without_literal_study_abroad_word(self):
        results=execute_plan(self.plan,[self.sheet],all_records=True)
        stats=verify_candidates('找海外教育背景研究人员',self.plan,results,self.decisions)
        self.assertEqual(stats['supported'],1)
        self.assertEqual(stats['unknown'],1)
        self.assertEqual(results[0]['records'][0]['fields']['姓名'],'研究员甲')
        self.assertIn('悉尼大学物理学博士',results[0]['records'][0]['fields']['条件核验依据'])
        self.assertEqual(stats['related'][0]['name'],'经理乙')
        self.assertEqual(stats['related'][0]['unconfirmed'],['研究托卡马克等离子体物理'])

    def test_invented_evidence_and_missing_condition_rejected(self):
        for kind in ('quote','condition','id'):
            def bad(payload):
                response=json.loads(self.decisions(payload))
                if kind=='quote':response['decisions'][0]['conditions'][0]['evidence'][0]['quote']='虚构的研究成果'
                if kind=='condition':response['decisions'][0]['conditions'].pop()
                if kind=='id':response['decisions'][0]['id']='invented'
                return json.dumps(response)
            with self.subTest(kind=kind):
                if kind=='id':
                    with self.assertRaises(ValueError):
                        verify_candidates('test',self.plan,execute_plan(self.plan,[self.sheet]),bad)
                else:
                    results=execute_plan(self.plan,[self.sheet])
                    stats=verify_candidates('test',self.plan,results,bad)
                    self.assertEqual(stats['unverified'],1)
                    self.assertEqual(stats['supported'],0)
                    self.assertEqual(results[0]['records'],[])

    def test_sort_fallback_does_not_reintroduce_unverified_people(self):
        plan=self.plan.model_copy(update={'sort_by':'OpenAlex h-index'})
        with patch('app.services.talent_search.read_talent_sheets',return_value=([self.sheet],[])):
            evidence=json.loads(talent_context('test',[],self.decisions,saved_plan=plan))
        self.assertEqual(evidence['matched'],1)
        self.assertTrue(evidence['unranked'])
        self.assertEqual([r['fields']['姓名'] for r in evidence['results'][0]['records']],['研究员甲'])

    def test_numeric_filter_and_concepts_remain_and_not_or(self):
        from app.services.talent_search import TalentFilter
        plan=self.plan.model_copy(update={'filters':[TalentFilter(field='当前机构',value='海外大学')]})
        self.assertEqual(execute_plan(plan,[self.sheet])[0]['matched_records'],1)

    def test_over_budget_candidates_do_not_silently_return_partial_matches(self):
        self.sheet.rows=self.rows[:1]*61
        with self.assertRaises(ValueError):
            verify_candidates('test',self.plan,execute_plan(self.plan,[self.sheet],all_records=True),self.decisions)

    def test_missing_candidate_is_retried_without_repeating_complete_rows(self):
        calls=[]
        def planner(payload):
            calls.append([row['id'] for row in payload['candidates']])
            response=json.loads(self.decisions(payload))
            if len(calls)==1:
                response['decisions']=response['decisions'][:1]
            return json.dumps(response)
        stats=verify_candidates('test',self.plan,execute_plan(self.plan,[self.sheet]),planner)
        self.assertEqual(calls,[['0','1'],['1']])
        self.assertEqual(stats['supported'],1)
        self.assertEqual(stats['unknown'],1)

    def test_invalid_json_recovery_is_bounded(self):
        calls=[]
        def planner(payload):
            calls.append(payload)
            return 'invalid json'
        stats=verify_candidates('test',self.plan,execute_plan(self.plan,[self.sheet]),planner)
        self.assertEqual(len(calls),2)
        self.assertEqual(stats['unverified'],2)
        self.assertEqual(stats['supported'],0)

    def test_batches_fit_remaining_operation_budget(self):
        from app.core.security import usage_counter
        self.sheet.rows=self.rows[:1]*13
        calls=[]
        def planner(payload):
            calls.append(len(payload['candidates']))
            return self.decisions(payload)
        token=usage_counter.set({'dispatched':1})
        try:
            stats=verify_candidates('test',self.plan,execute_plan(self.plan,[self.sheet],all_records=True),planner)
            self.assertEqual(calls,[6,6,1])
            self.assertEqual(stats['supported'],13)
            usage_counter.set({'dispatched':2})
            with self.assertRaises(ValueError):
                verify_candidates('test',self.plan,execute_plan(self.plan,[self.sheet],all_records=True),planner)
            self.assertEqual(calls,[6,6,1])
        finally:
            usage_counter.reset(token)

    def test_quote_typography_preserves_original_without_accepting_rewording(self):
        from app.services.talent_evidence import original_quote
        self.assertEqual(original_quote('A Chancellor’s Professor', "Chancellor's Professor"),'Chancellor’s Professor')
        self.assertIsNone(original_quote('A Chancellor’s Professor','Chancellor Professor'))

    def test_actual_failure_duplicate_keys_recovers_batch_within_budget(self):
        from app.core.security import usage_counter
        self.sheet.rows=self.rows[:1]*7
        calls=[]
        counter={'dispatched':1}  # 查询规划已消耗一次调用。
        def planner(payload):
            self.assertLess(counter['dispatched'],4)
            counter['dispatched']+=1
            calls.append([row['id'] for row in payload['candidates']])
            response=self.decisions(payload)
            if len(calls)==1:
                one=json.loads(response)['decisions'][:1]
                return '{"decisions":'+json.dumps(one)+',"decisions":'+json.dumps(one)+'}'
            return response
        token=usage_counter.set(counter)
        try:
            stats=verify_candidates('test',self.plan,execute_plan(self.plan,[self.sheet],all_records=True),planner)
        finally:
            usage_counter.reset(token)
        self.assertEqual([len(x) for x in calls],[6,6,1])
        self.assertEqual(stats['supported'],7)
        self.assertEqual(stats['unverified'],0)

    def test_multiple_missing_rows_retried_together(self):
        self.sheet.rows=self.rows[:1]*6
        calls=[]
        def planner(payload):
            calls.append([row['id'] for row in payload['candidates']])
            response=json.loads(self.decisions(payload))
            if len(calls)==1:
                response['decisions']=response['decisions'][:1]
            return json.dumps(response)
        stats=verify_candidates('test',self.plan,execute_plan(self.plan,[self.sheet],all_records=True),planner)
        self.assertEqual(calls,[['0','1','2','3','4','5'],['1','2','3','4','5']])
        self.assertEqual(stats['supported'],6)

    def test_retry_does_not_starve_later_batches_or_discard_valid_matches(self):
        from app.core.security import usage_counter
        from app.services.talent_answer import render_talent_answer
        self.sheet.rows=self.rows[:1]*13
        calls=[]
        counter={'dispatched':1}
        def planner(payload):
            self.assertLess(counter['dispatched'],4)
            counter['dispatched']+=1
            calls.append([row['id'] for row in payload['candidates']])
            response=json.loads(self.decisions(payload))
            if len(calls)==1:
                response['decisions']=response['decisions'][:1]
            return json.dumps(response)
        token=usage_counter.set(counter)
        try:
            results=execute_plan(self.plan,[self.sheet],all_records=True)
            stats=verify_candidates('test',self.plan,results,planner)
        finally:
            usage_counter.reset(token)
        self.assertEqual([len(x) for x in calls],[6,6,1])
        self.assertEqual(stats['supported'],8)
        self.assertEqual(stats['unverified'],5)
        self.assertEqual(stats['unknown'],0)
        self.assertEqual(results[0]['matched_records'],8)
        evidence={'pagination':{'returned':0,'has_more':False},'plan':self.plan.model_dump(),
                  'matched':8,'unranked':False,'results':results,'verification':stats}
        self.assertIn('5 条候选因模型响应异常或调用预算限制未完成核验',render_talent_answer(evidence,[]))
