import json
import unittest
from unittest.mock import Mock,patch
from app.services.talent_search import TalentFilter,TalentPlan,TalentConcept,TalentSheet,protect_text_filters,validate_plan,execute_plan,talent_context
from app.services.talent_results import load_result

class TalentReviewTests(unittest.TestCase):
    def setUp(self):
        self.sheet=TalentSheet('source','people.xlsx','Sheet1',['姓名','当前机构','当前职务','详细个人简介','教育经历'],[
            {'row':2,'fields':{'姓名':'联合聘任者','当前机构':'A大学','当前职务':'电气与计算机工程系双聘助理教授'}},
            {'row':3,'fields':{'姓名':'该专业毕业生','当前机构':'B公司','教育经历':'计算机工程系博士'}},
            {'row':4,'fields':{'姓名':'现任教师','当前机构':'C大学计算机工程系'}},
        ])
        self.plan=TalentPlan(filters=[TalentFilter(field='当前机构',value='计算机工程系')])

    def test_column_filter_cannot_drop_fact_recorded_in_other_fields(self):
        safe=protect_text_filters(self.plan,'找计算机工程系人才',[self.sheet])
        self.assertEqual(safe.filters,[])
        self.assertIn('当前',safe.evidence_conditions[0])
        self.assertEqual(len(execute_plan(safe,[self.sheet])[0]['records']),3)
        def verifier(payload):
            decisions=[]
            for item in payload['candidates']:
                current=[p for p in item['passages'] if p['field'] in {'当前机构','当前职务'} and '计算机工程系' in p['quote']]
                decisions.append({'id':item['id'],'checks':[{'status':'supported' if current else 'contradicted','refs':[current[0]['id']] if current else []}]})
            return json.dumps({'decisions':decisions})
        with patch('app.services.talent_search.read_talent_sheets',return_value=([self.sheet],[])):
            result=json.loads(talent_context('找计算机工程系人才',[],verifier,saved_plan=safe))
        self.assertEqual([r['fields']['姓名'] for r in result['results'][0]['records']],['联合聘任者','现任教师'])

    def test_explicit_literal_column_request_remains_literal(self):
        plan=self.plan.model_copy(update={'filters':[TalentFilter(field='当前机构',value='计算机工程系',literal=True)]})
        safe=protect_text_filters(plan,'当前机构列包含计算机工程系',[self.sheet])
        self.assertEqual(len(safe.filters),1)
        self.assertEqual(len(execute_plan(safe,[self.sheet])[0]['records']),1)
        guarded=protect_text_filters(plan,'找计算机工程系人才',[self.sheet])
        self.assertEqual(guarded.filters,[])

    def test_unknown_literal_value_gets_semantic_recall_not_silent_zero(self):
        plan=TalentPlan(filters=[TalentFilter(field='当前机构',value='Department of Computer Engineering')])
        safe=protect_text_filters(plan,'找Computer Engineering人才',[self.sheet])
        self.assertTrue(safe.concepts)
        self.assertTrue(safe.evidence_conditions)

    def test_expansion_without_constraints_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_plan(TalentPlan(concepts=[TalentConcept(fields=['当前职务'],terms=['工程'])]),[self.sheet])

    def test_verified_pagination_reuses_order_without_more_model_calls(self):
        plan=validate_plan(TalentPlan(concepts=[TalentConcept(fields=['当前机构'],terms=['大学'])],
            evidence_conditions=['当前任职大学']),[self.sheet])
        def verify(payload):
            return json.dumps({'decisions':[{'id':r['id'],'checks':[{'status':'supported','refs':[next(p['id'] for p in r['passages'] if p['field']=='当前机构')]}]} for r in payload['candidates']]})
        scope=('user-a','base-a','revision-1')
        with patch('app.services.talent_search.read_talent_sheets',return_value=([self.sheet],[])):
            first=json.loads(talent_context('大学人才',[],verify,saved_plan=plan,max_results=1,snapshot_scope=scope))
        self.assertTrue(first['snapshot_id'])
        saved=TalentPlan.model_validate(first['plan'])
        planner=Mock(side_effect=AssertionError('Pagination must not call model'))
        with patch('app.services.talent_search.read_talent_sheets',side_effect=AssertionError('Pagination must not read full rows')):
            second=json.loads(talent_context('大学人才',[],planner,saved_plan=saved,offset=1,max_results=1,
                snapshot_id=first['snapshot_id'],snapshot_scope=scope))
        self.assertEqual(second['results'][0]['records'][0]['fields']['姓名'],'现任教师')
        self.assertFalse(second['pagination']['has_more'])
        self.assertIsNone(load_result(first['snapshot_id'],('user-b','base-a','revision-1'),'大学人才',first['plan']))
        self.assertIsNone(load_result(first['snapshot_id'],('user-a','base-a','revision-2'),'大学人才',first['plan']))
        self.assertIsNone(load_result(first['snapshot_id'],scope,'另一个查询',first['plan']))
        self.assertIsNone(load_result(first['snapshot_id'],scope,'大学人才',{}))
        with patch('app.services.talent_results.time.monotonic',return_value=float('inf')):
            self.assertIsNone(load_result(first['snapshot_id'],scope,'大学人才',first['plan']))

    def test_long_profile_keeps_late_evidence_and_quotes_remain_verbatim(self):
        from app.services.talent_evidence import evidence_passages
        fields={'姓名':'长履历人员','详细个人简介':'早期项目经历。'*500+'目前为工程学院联合聘任教授。',
                '教育经历':'本科国内大学；博士——美国某大学'}
        passages=evidence_passages(fields,['联合聘任'],budget=2000)
        self.assertTrue(any('联合聘任教授' in p['quote'] for p in passages))
        self.assertTrue(any('美国某大学' in p['quote'] for p in passages))
        self.assertLessEqual(sum(len(p['quote']) for p in passages),2000)
        self.assertTrue(all(p['quote'] in fields[p['field']] for p in passages))

    def test_one_bad_quote_does_not_remove_other_valid_people(self):
        from app.services.talent_evidence import verify_candidates
        plan=TalentPlan(evidence_conditions=['当前任职大学'])
        results=[{'file':'people.xlsx','sheet':'Sheet1','records':[
            {'excel_row':2,'fields':{'姓名':'坏证据','当前机构':'A大学'}},
            {'excel_row':3,'fields':{'姓名':'好证据','当前机构':'B大学'}}]}]
        def planner(payload):
            return json.dumps({'decisions':[{'id':r['id'],'conditions':[{'condition':0,'status':'supported',
                'evidence':[{'field':'当前机构','quote':'虚构大学' if r['id']=='0' else 'B大学'}]}]} for r in payload['candidates']]})
        stats=verify_candidates('大学人才',plan,results,planner)
        self.assertEqual(stats['unverified'],1)
        self.assertEqual(stats['supported'],1)
        self.assertEqual(results[0]['records'][0]['fields']['姓名'],'好证据')

    def test_partial_semantic_recall_cannot_be_reported_as_global_ranking(self):
        self.sheet.headers.append('OpenAlex h-index')
        for row,value in zip(self.sheet.rows,['9','100','22']):
            row['fields']['OpenAlex h-index']=value
        plan=TalentPlan(concepts=[TalentConcept(fields=['当前职务'],terms=['工程'])],
            evidence_conditions=['当前任职工程系'],sort_by='OpenAlex h-index')
        def planner(payload):
            decisions=[]
            for item in payload['candidates']:
                proof=[p for p in item['passages'] if p['field'] in {'当前机构','当前职务'} and '工程系' in p['quote']]
                decisions.append({'id':item['id'],'checks':[{'status':'supported' if proof else 'contradicted',
                    'refs':[proof[0]['id']] if proof else []}]})
            return json.dumps({'decisions':decisions})
        rows=[{'excel_row':r['row'],'fields':dict(r['fields'])} for r in self.sheet.rows]
        groups=[{'source_id':'source','file':'people.xlsx','sheet':'Sheet1','records':rows,'matched_records':3}]
        with patch('app.services.talent_search.read_talent_sheets',return_value=([self.sheet],[])):
            result=json.loads(talent_context('工程系按OpenAlex h-index排名',[],planner,saved_plan=plan,
                hybrid_search=lambda *args:(groups,{'limited':True})))
        self.assertEqual(result['ranking_scope'],'matched_results')
        self.assertEqual([r['fields']['姓名'] for r in result['results'][0]['records']],['现任教师','联合聘任者'])
        self.assertEqual(result['rankable'],2)
        from app.services.talent_answer import render_talent_answer
        self.assertIn('不代表全库排名',render_talent_answer(result,[]))

    def test_multiple_valid_references_do_not_discard_verified_candidates(self):
        from app.services.talent_evidence import verify_candidates
        plan=TalentPlan(evidence_conditions=['海外大学任职'])
        results=[{'source_id':'s','file':'test.xlsx','sheet':'Sheet1','records':[
            {'excel_row':2,'fields':{'姓名':'甲教授','当前机构':'美国大学','当前职务':'助理教授','工作经历':'海外大学工作'}}]}]
        def planner(payload):
            item=payload['candidates'][0]
            return json.dumps({'decisions':[{'id':item['id'],'checks':[{'status':'supported',
                'refs':[p['id'] for p in item['passages']]}]}]})
        stats=verify_candidates('海外大学任职',plan,results,planner)
        self.assertEqual(stats['supported'],1)
        self.assertEqual(stats['unverified'],0)
