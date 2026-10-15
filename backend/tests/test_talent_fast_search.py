import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch, Mock
from app.services.talent_search import TalentPlan, TalentSheet, validate_plan, talent_context
from app.services.talent_search_schema import SearchSpec, SearchPredicate
from app.services.talent_fast_search import search_talents
from app.services.talent_results import load_result


class FastSearchTests(unittest.TestCase):
    def setUp(self):
        self.sheet=TalentSheet('source','people.xlsx','S',['姓名','所在国家／城市','研究方向','OpenAlex h-index'],[
            {'row':i+2,'talent_id':str(i),'fields':{'姓名':f'person-{i}','所在国家／城市':region,
                '研究方向':topic,'OpenAlex h-index':metric}}
            for i,(region,topic,metric) in enumerate([
                ('美国／城市A','protein design','5'),('中国／城市B','protein','99'),
                ('新加坡／城市C','tokamak engineering',''),('','protein','9'),
                ('美国／城市D','unrelated discipline','100'),('美国／城市E','protein tokamak','0')])])
        self.plan=validate_plan(TalentPlan(evidence_conditions=['current overseas'],topic_condition='protein or tokamak',
            search=SearchSpec(predicates=[
                SearchPredicate(condition='current overseas',kind='metadata',fields=['@current_region'],op='equals_any',values=['美国','新加坡']),
                SearchPredicate(condition='protein or tokamak',kind='topic',fields=['研究方向'],values=['protein','tokamak'])])),[self.sheet])
        self.scope=('user','base','revision')
        self.planner=Mock(side_effect=AssertionError('No per-person model calls'))
        self.planner.search_db=None
        self.planner.search_base='base'

    def run_search(self, plan=None, size=10):
        with patch('app.services.talent_fast_search.ready_index',return_value=(None,'warming')):
            return json.loads(search_talents('query',plan or self.plan,[self.sheet],[],self.planner,self.scope,0,size))

    def test_filters_and_union_recall_return_only_related_people(self):
        result=self.run_search()
        names={r['fields']['姓名'] for g in result['results'] for r in g['records']}
        self.assertEqual(names,{'person-0','person-2','person-5'})
        self.assertEqual(result['coverage']['unknown'],1)
        self.assertEqual(result['search_mode'],'hybrid')
        self.assertFalse(result['coverage']['complete'])
        self.planner.assert_not_called()

    def test_metric_sort_preserves_missing_and_zero_and_pages_without_models(self):
        plan=self.plan.model_copy(update={'sort_by':'OpenAlex h-index'})
        result=self.run_search(plan,size=2)
        self.assertEqual([r['fields']['姓名'] for g in result['results'] for r in g['records']],['person-0','person-5'])
        with patch('app.services.talent_search.read_talent_sheets',side_effect=AssertionError('No reread')),patch('app.services.talent_execution.resume_search',side_effect=AssertionError('No verification')):
            page=json.loads(talent_context('query',[],self.planner,saved_plan=plan,snapshot_scope=self.scope,
                snapshot_id=result['snapshot_id'],offset=2,max_results=2))
        self.assertEqual(page['results'][0]['records'][0]['fields']['姓名'],'person-2')
        self.assertFalse(page['pagination']['has_more'])

    def test_uncompiled_condition_is_explicit_not_silently_dropped(self):
        plan=self.plan.model_copy(update={'evidence_conditions':self.plan.evidence_conditions+['complex employment relation']})
        result=self.run_search(plan)
        self.assertEqual(result['unresolved_conditions'],['complex employment relation'])
        self.assertFalse(result['coverage']['complete'])

    def test_only_unresolved_condition_does_not_return_the_entire_database(self):
        plan=TalentPlan(evidence_conditions=['subjective potential'],search=SearchSpec(predicates=[
            SearchPredicate(condition='subjective potential',kind='unresolved')]))
        result=self.run_search(plan)
        self.assertEqual(result['matched'],0)
        self.assertEqual(result['unresolved_conditions'],['subjective potential'])

    def test_topic_intersection_requires_both_groups(self):
        from app.services.talent_search_schema import SearchSpec
        plan=TalentPlan(evidence_conditions=['a','b'],search=SearchSpec(predicates=[
            SearchPredicate(condition='a',kind='topic',fields=['研究方向'],values=['protein']),
            SearchPredicate(condition='b',kind='topic',fields=['研究方向'],values=['tokamak'])]))
        result=self.run_search(plan)
        self.assertEqual(result['matched'],1)
        self.assertEqual(result['results'][0]['records'][0]['fields']['姓名'],'person-5')

    def test_unscoped_snapshot_is_not_reusable_by_another_user(self):
        result=self.run_search()
        self.assertIsNone(load_result(result['snapshot_id'],('different-user','base','revision'),'query',result['plan']))

    def test_invalid_compiled_predicate_is_rejected(self):
        p=self.plan.model_copy(deep=True)
        p.search.predicates[0].fields=['invented-field']
        with self.assertRaises(ValueError):self.run_search(p)

    def test_dense_and_related_terms_cannot_admit_unrelated_people(self):
        import numpy as np
        plan=self.plan.model_copy(deep=True)
        plan.search.predicates[1].related_values=['unrelated discipline']
        # Deliberately give the irrelevant person the strongest vector score.
        ids=[str(i) for i in range(6)]
        matrix=np.array([[.1,.99],[.1,.99],[.1,.99],[.1,.99],[1.,0.],[.1,.99]])
        with patch('app.services.talent_fast_search.ready_index',return_value=((ids,matrix),'ready')), \
             patch('app.services.talent_fast_search.EmbeddingClient.embed_text',return_value=[1.,0.]) as embedding:
            result=json.loads(search_talents('query',plan,[self.sheet],[],self.planner,self.scope,0,10))
        embedding.assert_called_once_with('protein tokamak')
        self.assertEqual({r['fields']['姓名'] for g in result['results'] for r in g['records']},
                         {'person-0','person-2','person-5'})
        self.assertEqual(result['retrieval']['vector_status'],'ready')
        self.assertGreater(result['retrieval']['unsupported_candidates'],0)

    def test_unknown_topic_does_not_fill_page_with_nearest_neighbours(self):
        import numpy as np
        plan=validate_plan(TalentPlan(topic_condition='novel specialty',search=SearchSpec(predicates=[
            SearchPredicate(condition='novel specialty',kind='topic',fields=['研究方向'],
                            values=['novel specialty'],related_values=['protein'])])),[self.sheet])
        with patch('app.services.talent_fast_search.ready_index',return_value=((['0'],np.array([[1.,0.]])),'ready')), \
             patch('app.services.talent_fast_search.EmbeddingClient.embed_text',return_value=[1.,0.]):
            result=json.loads(search_talents('query',plan,[self.sheet],[],self.planner,self.scope,0,10))
        self.assertEqual(result['matched'],0)
        self.assertGreater(result['retrieval']['unsupported_candidates'],0)

    def test_full_original_achievements_are_used_even_when_index_profile_is_short(self):
        self.sheet.headers.append('代表成果')
        self.sheet.rows[4]['fields']['代表成果']='other information '*600+'protein engineering'
        result=self.run_search()
        row=next(r for g in result['results'] for r in g['records'] if r['fields']['姓名']=='person-4')
        self.assertIn('protein engineering',row['fields']['检索依据'])


class FastSearchApiTests(unittest.TestCase):
    import test_workspace as workspace
    setUp=workspace.WorkspaceTests.setUp
    tearDown=workspace.WorkspaceTests.tearDown
    base=workspace.WorkspaceTests.base

    def test_api_search_followup_and_paging_do_not_verify_people(self):
        import io
        from openpyxl import Workbook
        from app.ai.providers.openai_compatible import OpenAICompatibleProvider
        from app.schemas.usage import ChatResult,TokenUsage
        base=self.base();book=Workbook();sheet=book.active
        sheet.append(['姓名','当前机构','所在国家／城市','研究方向','OpenAlex h-index'])
        sheet.append(['A','Institute','美国／A','protein',5])
        sheet.append(['B','Institute','美国／B','tokamak',None])
        sheet.append(['C','Institute','中国／C','protein',100])
        content=io.BytesIO();book.save(content);book.close()
        response=self.client.post(f'/api/knowledge/bases/{base}/upload',files={'file':('people.xlsx',content.getvalue(),'application/octet-stream')})
        self.assertEqual(response.status_code,201,response.text)
        plan={'search':{'predicates':[
            {'condition':'overseas','kind':'metadata','fields':['@current_region'],'op':'equals_any','values':['美国']},
            {'condition':'protein or tokamak','kind':'topic','fields':['研究方向'],'values':['protein','tokamak']}]}}
        history=[]
        def answer(config,messages,model,key):
            question=json.loads(messages[-1].content)['question']
            return ChatResult(content=json.dumps({'sort_by':'OpenAlex h-index'} if '排序' in question else plan),usage=TokenUsage())
        with patch('app.services.talent_fast_search.ready_index',return_value=(None,'warming')), \
             patch.object(OpenAICompatibleProvider,'chat',side_effect=answer) as model, \
             patch.object(OpenAICompatibleProvider,'_chat_reserved',side_effect=AssertionError('No candidate verification')):
            first=self.client.post('/api/knowledge/ask',json={'question':'海外蛋白质或托卡马克人才','knowledge_base_id':base,'talent_page_size':1}).json()
            self.assertEqual(len(first['row_sources']),1)
            self.assertEqual(model.call_count,1)
            self.assertNotIn('已核验',first['answer'])
            history.append({'question':'海外蛋白质或托卡马克人才','answer':first['answer'],'query_state':first['query_state']})
            second=self.client.post('/api/knowledge/ask',json={'question':'下一页','knowledge_base_id':base,'history':history}).json()
            self.assertEqual(model.call_count,1)
            names={first['row_sources'][0]['fields']['姓名'],second['row_sources'][0]['fields']['姓名']}
            self.assertEqual(names,{'A','B'})
            sorted_result=self.client.post('/api/knowledge/ask',json={'question':'按OpenAlex h-index排序','knowledge_base_id':base,'history':history}).json()
            self.assertEqual(model.call_count,1)  # Sorting adds no model request.
            self.assertEqual([r['fields']['姓名'] for r in sorted_result['row_sources']],['A','B'])
            self.assertEqual(sorted_result['query_state']['plan']['evidence_conditions'],['overseas','protein or tokamak'])


class TopicCompilerTests(unittest.TestCase):
    def test_explicit_any_and_all_compile_without_topic_specific_branches(self):
        sheet=TalentSheet('s','f','t',['姓名','研究方向'],[
            {'row':2,'fields':{'姓名':'A','研究方向':'alpha'}},
            {'row':3,'fields':{'姓名':'B','研究方向':'beta'}},
            {'row':4,'fields':{'姓名':'C','研究方向':'alpha beta'}}])
        for mode,expected in [('any',3),('all',1)]:
            def planner(schema):
                return json.dumps({'search':{'topic_mode':mode,'predicates':[
                    {'condition':'first topic','kind':'topic','fields':['研究方向'],'values':['alpha']},
                    {'condition':'second topic','kind':'topic','fields':['研究方向'],'values':['beta']}]}})
            planner.fast_search=True;planner.search_db=None;planner.search_base=None
            with patch('app.services.talent_search.read_talent_sheets',return_value=([sheet],[])):
                result=json.loads(talent_context('find people',[],planner,max_results=10))
            self.assertEqual(result['matched'],expected)

    def test_current_region_does_not_use_past_education(self):
        from app.services.talent_fast_search import test_predicate
        predicate=SearchPredicate(condition='region',kind='metadata',fields=['@current_region'],op='equals_any',values=['美国'])
        self.assertFalse(test_predicate({'所在国家／城市':'中国／上海','教育经历':'美国博士'},predicate))
        self.assertIsNone(test_predicate({'教育经历':'美国博士'},predicate))
