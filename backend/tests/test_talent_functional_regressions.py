"""Regression journeys for the semantic compiler, state transitions and counts."""
import io
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from openpyxl import Workbook
import test_workspace as workspace
from app.ai.providers.openai_compatible import OpenAICompatibleProvider
from app.schemas.usage import ChatResult, TokenUsage
from app.services.talent_search import TalentSheet
from app.services.talent_semantics import compile_intent, bind_semantics, local_metric_intent
from app.services.talent_fast_search import search_talents

INDEX='OpenAlex h-index'
CITATIONS='OpenAlex总引用数'


def metric(field, op='gte', value='10', mode='add'):
    return {'slot':'metric','field':field,'op':op,'values':[value],'mode':mode,'evidence':field+'至少'+value}


class StateJourneyTests(unittest.TestCase):
    setUp=workspace.WorkspaceTests.setUp
    tearDown=workspace.WorkspaceTests.tearDown
    base=workspace.WorkspaceTests.base

    def roster(self):
        base=self.base();book=Workbook();sheet=book.active
        sheet.append(['姓名','领域','当前机构','所在国家／城市',INDEX,CITATIONS])
        for row in [['A','AI4S','Example University','英国',20,20],
                    ['B','other','Example University','英国',5,20],
                    ['C','AI4S','Other University','美国',30,5],
                    ['D','AI4S','Other University','美国',40,40]]:sheet.append(row)
        output=io.BytesIO();book.save(output)
        response=self.client.post(f'/api/knowledge/bases/{base}/upload',files={'file':('synthetic.xlsx',output.getvalue(),'application/octet-stream')})
        self.assertEqual(response.status_code,201,response.text)
        return base

    @contextmanager
    def models(self,*plans):
        queued=iter(plans)
        def model(config,messages,model,key):
            data=json.loads(messages[-1].content)
            phase=data.get('schema',{}).get('phase')
            self.assertNotEqual(phase,'verify_candidates','Ordinary queries must never verify people with a model')
            result={'verdict':'supported'} if phase=='review_context_update' else next(queued)
            return ChatResult(content=json.dumps(result),usage=TokenUsage())
        with patch.object(OpenAICompatibleProvider,'chat',side_effect=model) as calls, \
             patch('app.services.talent_fast_search.ready_index',return_value=(None,'disabled')):
            yield calls

    def ask(self,base,question,history,endpoint='/api/knowledge/ask'):
        response=self.client.post(endpoint,json={'question':question,'knowledge_base_id':base,'history':history})
        self.assertEqual(response.status_code,200,response.text)
        if endpoint.endswith('/stream'):
            events={}
            for block in response.text.strip().split('\n\n'):
                lines=block.splitlines();events[lines[0][7:]]=json.loads(lines[1][6:])
            self.assertIn('done',events)
            result={**events['meta'],'answer':events['delta']['text']}
        else:result=response.json()
        history.append({'question':question,'answer':result['answer'],'query_state':result.get('query_state')})
        return result

    def names(self,result):return {row['fields']['姓名'] for row in result['row_sources']}

    def test_page_scope_uses_the_previous_displayed_rows(self):
        base=self.roster();history=[]
        with self.models({'operation':'count','result_scope':'previous_page'}):
            first=self.ask(base,'查找AI4S领域人才',history)
            # Select an actual page containing A and C, leaving D outside.
            history[-1]['query_state'].update(offset=0,returned=2)
            result=self.ask(base,'这一页共有多少人',history)
            self.assertIn('共 2 条',result['answer'])
        # Direct scope contracts below exercise replacement without inventing UI offsets.

    def test_metric_constraints_keep_field_and_operator_identity(self):
        base=self.roster();history=[]
        with self.models({'facets':[metric(INDEX)]},{'facets':[metric(CITATIONS)]}):
            self.assertEqual(self.names(self.ask(base,INDEX+'至少10',history)),{'A','C','D'})
            result=self.ask(base,CITATIONS+'至少10',history)
            self.assertEqual(self.names(result),{'A','D'})
            self.assertEqual(len(result['query_state']['plan']['search']['predicates']),2)
        with self.models({'facets':[metric(INDEX),metric(CITATIONS)]}):
            result=self.ask(base,INDEX+'至少10，'+CITATIONS+'至少10',[])
            self.assertEqual(self.names(result),{'A','D'})
        # Identical values on opposite sides are a valid interval, not duplicate conditions.
        lower=metric(INDEX);upper=metric(INDEX,'lte');upper['evidence']=INDEX+'至多10'
        with self.models({'facets':[lower,upper]}):
            result=self.ask(base,INDEX+'至少10且'+INDEX+'至多10',[])
            self.assertEqual(self.names(result),set())

    def test_explicit_metric_comparisons_execute_without_a_model(self):
        base=self.roster();history=[]
        with self.models() as calls:
            self.ask(base,INDEX+'至少10的人才',history)
            result=self.ask(base,'并且'+CITATIONS+'至少10',history)
            self.assertEqual(self.names(result),{'A','D'})
            calls.assert_not_called()

    def test_remove_topic_keeps_geography_and_removes_its_execution_predicate(self):
        base=self.roster();history=[]
        with self.models({'facets':[{'slot':'current_region','values':['英国'],'evidence':'英国'},
                                    {'slot':'topic','values':['AI4S'],'evidence':'AI4S'}]},
                         {'remove':['topic'],'evidence':'取消领域限制'}):
            self.assertEqual(self.names(self.ask(base,'英国的AI4S人才',history)),{'A'})
            result=self.ask(base,'取消领域限制',history)
            self.assertEqual(self.names(result),{'A','B'})
            self.assertEqual(result['query_state']['plan']['topic_condition'],'')
            self.assertEqual([p['slot'] for p in result['query_state']['plan']['search']['predicates']],['current_region'])

    def test_reset_keeps_new_sort_and_limit_then_controls_can_clear_them(self):
        base=self.roster();history=[]
        question='重新开始，按OpenAlex h-index排序，前2名'
        with self.models({'reset':True,'evidence':'重新开始','sort_by':INDEX,'result_limit':2},
                         {'clear_sort':True,'clear_limit':True,'evidence':'取消排序和人数限制'},
                         {'reset':True,'evidence':'重新开始'}):
            self.ask(base,'英国人才',history)
            result=self.ask(base,question,history)
            self.assertEqual([r['fields']['姓名'] for r in result['row_sources']],['D','C'])
            self.assertEqual(result['query_state']['plan']['result_limit'],2)
            result=self.ask(base,'取消排序和人数限制',history)
            self.assertEqual(self.names(result),{'A','B','C','D'})
            self.assertIsNone(result['query_state']['plan']['sort_by'])
            self.assertIsNone(result['query_state']['plan']['result_limit'])
            result=self.ask(base,'重新开始',history)
            self.assertEqual(self.names(result),{'A','B','C','D'})

    def test_geo_clarification_preserves_state_for_json_and_streaming(self):
        base=self.roster()
        for endpoint in ['/api/knowledge/ask','/api/knowledge/ask/stream']:
            history=[]
            with self.models() as calls:
                original=self.ask(base,'英国人才',history,endpoint)
                clarified=self.ask(base,'按所在地筛选',history,endpoint)
                self.assertIn('哪个国家或城市',clarified['answer'])
                self.assertEqual(clarified['query_state'],original['query_state'])
                result=self.ask(base,'美国人才',history,endpoint)
                self.assertEqual(self.names(result),{'C','D'})
                calls.assert_not_called()

    def test_filtered_count_and_followup_keep_scope_without_per_person_calls(self):
        base=self.roster();history=[]
        with self.models({'operation':'count'},{'operation':'count'}):
            self.ask(base,'英国人才',history)
            result=self.ask(base,'这些人才一共多少',history)
            self.assertIn('共 2 条',result['answer'])
            self.assertIsNotNone(result['query_state'])
            self.assertTrue(result['talent_coverage']['complete'])
            result=self.ask(base,'美国人才',history)
            self.assertIn('共 2 条',result['answer'])
            self.assertEqual(result['query_state']['plan']['intent'],'aggregate')
            result=self.ask(base,'查找美国人才',history)
            self.assertEqual(self.names(result),{'C','D'})
            result=self.ask(base,'这些人才一共多少',history)
            self.assertIn('共 2 条',result['answer'])


class DeterministicCountTests(unittest.TestCase):
    def setUp(self):
        self.sheet=TalentSheet('s','f','people',['姓名','领域','当前机构','所在国家／城市',INDEX,CITATIONS],[
            {'row':i+2,'fields':{'姓名':f'person-{i}','领域':'AI4S','当前机构':'Example University',
                              '所在国家／城市':'UK' if i%2 else '美国',INDEX:'20',CITATIONS:'10'}} for i in range(80)])

    def run_count(self,data,question):
        plan=compile_intent(data,question,[self.sheet])
        with patch('app.services.talent_fast_search.ready_index',side_effect=AssertionError('No embeddings for counts')), \
             patch('app.services.talent_execution.verify_candidates',side_effect=AssertionError('No model verification for counts')):
            return json.loads(search_talents(question,plan,[self.sheet],[],SimpleNamespace(),('count-test',),0,5))

    def test_topic_count_is_not_limited_by_recall_or_page_size(self):
        result=self.run_count({'operation':'count','result_limit':1,'facets':[
            {'slot':'topic','values':['AI4S'],'evidence':'AI4S'}]},'AI4S')
        self.assertEqual(result['aggregate']['records'],80)
        self.assertIn('不能保证语义穷尽',result['aggregate']['basis'])
        self.assertFalse(result['coverage']['complete'])

    def test_structured_group_and_distinct_counts_use_the_filtered_set(self):
        for operation in ['count','distinct_count','group_count']:
            data={'operation':operation,'field':'当前机构','facets':[{'slot':'current_region','values':['英国'],'evidence':'英国'}]}
            result=self.run_count(data,'英国')
            self.assertEqual(result['aggregate']['records'],40)
            self.assertEqual(result['aggregate']['groups'],{'Example University':40})
            self.assertTrue(result['coverage']['complete'])

    def test_unavailable_hard_conditions_do_not_produce_an_aggregate(self):
        result=self.run_count({'operation':'count','facets':[{'slot':'institution_country','values':['英国'],'evidence':'英国'}]},'英国院校')
        self.assertNotIn('aggregate',result)
        self.assertEqual(result['matched'],0)
        self.assertTrue(result['unresolved_conditions'])
        self.assertFalse(result['coverage']['complete'])

    def test_unknown_metadata_is_reported_without_certifying_an_exact_total(self):
        self.sheet.rows[1]['fields']['所在国家／城市']=''
        result=self.run_count({'operation':'count','facets':[{'slot':'current_region','values':['英国'],'evidence':'英国'}]},'英国')
        self.assertEqual(result['aggregate']['records'],39)
        self.assertEqual(result['coverage']['unknown'],1)
        self.assertFalse(result['coverage']['complete'])

    def test_metric_set_only_replaces_the_same_field_and_side(self):
        question=INDEX+'至少10，'+CITATIONS+'至少10'
        prior=compile_intent({'facets':[metric(INDEX),metric(CITATIONS)]},question,[self.sheet])
        current=compile_intent({'facets':[metric(INDEX,value='30',mode='set')]},INDEX+'至少30',[self.sheet],prior.model_dump())
        self.assertEqual(current.context_update.remove_conditions,[0])
        legacy=prior.model_copy(deep=True)
        legacy.search.predicates[0].condition='指标：10';legacy.evidence_conditions[0]='指标：10'
        self.assertEqual(bind_semantics(legacy,[self.sheet]),prior)

    def test_metric_grammar_is_schema_driven_and_does_not_drop_extra_constraints(self):
        fields=['Example h-index','Other总引用数']
        for phrase,op in [('至少','gte'),('不低于','gte'),('≥','gte'),('>=','gte'),
                          ('至多','lte'),('不超过','lte'),('≤','lte'),('<=','lte')]:
            for value in ['0','10','-2','.5']:
                question='请帮我筛选Example h-index'+phrase+value+'的人才'
                plan=local_metric_intent(question,fields)
                self.assertEqual(plan['facets'][0]['op'],op)
                self.assertEqual(plan['facets'][0]['values'],[value])
        plan=local_metric_intent('Example h-index>=10，并且Other总引用数≤20',fields)
        self.assertEqual(len(plan['facets']),2)
        self.assertEqual(local_metric_intent('改成Example h-index至少20',fields)['facets'][0]['mode'],'set')
        for question in ['Example h-index至少10但排除美国','Example h-index至少10或Other总引用数至少20',
                         'Example h-index至少10并且只要女性','h-index至少10','Other h-index至少10',
                         'Example h-index大于10','Example h-index至少10且有创业经历']:
            self.assertIsNone(local_metric_intent(question,fields),question)
