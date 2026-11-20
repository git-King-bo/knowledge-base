"""Semantic contracts: grounding, unavailable facts, and multi-turn state transitions."""
import io
import unittest
from unittest.mock import patch

from openpyxl import Workbook

import test_workspace as workspace
from app.ai.providers.openai_compatible import OpenAICompatibleProvider
from app.services.talent_search import TalentPlan, TalentSheet
from app.services.talent_search_schema import SearchPredicate, SearchSpec, bind_relations
from app.services.talent_context_update import inherit_plan, ContextChangeUnresolved
from app.services.talent_semantics import (
    COUNTRY_ALIASES, bind_semantics, compile_intent, institution_type, local_geo_intent,
)


def sheets():
    return [TalentSheet('s', 'f', 'people', [
        '姓名', '领域', '当前机构', '所在国家／城市', '工作经历', '教育经历', 'OpenAlex h-index',
    ], [])]


class SemanticContractTests(unittest.TestCase):
    def compile(self, data, question, previous=None):
        return compile_intent(data, question, sheets(), previous.model_dump() if previous else None)

    def test_optional_facets_do_not_select_the_legacy_decoder(self):
        import json
        from app.services.talent_search import parse_model_plan
        for data in [
            {'operation':'count'},
            {'operation':'distinct_count','field':'当前机构'},
            {'operation':'group_count','field':'所在国家／城市'},
            {'sort_by':'OpenAlex h-index'},
            {'reset':True,'evidence':'重新开始'},
        ]:
            with self.subTest(data=data):
                expected=self.compile(data,'重新开始')
                self.assertEqual(parse_model_plan(json.dumps(data),sheets=sheets(),question='重新开始'),expected)
        legacy=parse_model_plan('{"intent":"aggregate","operation":"count"}',sheets=sheets())
        self.assertEqual(legacy.intent,'aggregate')
        with self.assertRaises(ValueError):
            parse_model_plan('{"facets":[],"invented":true}',sheets=sheets())

    def test_country_grammar_across_all_aliases_is_complete_and_grounded(self):
        for canonical, aliases in COUNTRY_ALIASES.items():
            for alias in aliases:
                for tail, slot in [('人才', 'current_region'), ('院校的人才有么', 'institution_country')]:
                    question=alias+tail
                    with self.subTest(question=question):
                        plan=self.compile(local_geo_intent(question), question)
                        predicate=plan.search.predicates[0]
                        self.assertEqual((predicate.slot, predicate.values), (slot, [canonical]))
                        self.assertEqual(predicate.kind, 'unresolved' if slot=='institution_country' else 'metadata')
        for question in ['英国院校但排除博士', '美国人才并且曾经创业', '英国院校或美国公司', '不是美国人才']:
            self.assertIsNone(local_geo_intent(question), question)

    def test_legacy_country_as_institution_never_executes_and_binding_is_idempotent(self):
        plan=TalentPlan(evidence_conditions=['英国院校'], search=SearchSpec(predicates=[
            SearchPredicate(condition='英国院校', kind='metadata', fields=['当前机构'], values=['英国'], relation='current_affiliation')]))
        bound=bind_semantics(plan,sheets())
        self.assertEqual(bound.search.predicates[0].slot,'institution_country')
        self.assertEqual(bound.search.predicates[0].kind,'unresolved')
        self.assertEqual(bound.search.predicates[0].fields,[])
        self.assertEqual(bind_semantics(bound,sheets()),bound)
        self.assertEqual(plan.search.predicates[0].kind,'metadata')

    def test_explicit_country_columns_are_required_and_used(self):
        source=sheets()[0]; source.headers.append('机构国别')
        plan=compile_intent(local_geo_intent('英国院校'), '英国院校', [source])
        self.assertEqual(plan.search.predicates[0].fields,['机构国别'])
        self.assertEqual(plan.search.predicates[0].kind,'metadata')
        from app.services.talent_fast_search import test_predicate
        predicate=plan.search.predicates[0]
        self.assertTrue(test_predicate({'机构国别':'UK','所在国家／城市':'美国'},predicate))
        self.assertFalse(test_predicate({'机构国别':'美国','所在国家／城市':'英国'},predicate))
        self.assertIsNone(test_predicate({'所在国家／城市':'英国'},predicate))

    def test_type_classifier_uses_explicit_evidence_and_keeps_unknowns(self):
        for name in ['Northbridge University', 'Example College', '示例大学']:
            self.assertEqual(institution_type({'当前机构':name}),'university')
        for name in ['MIT', 'Example Lab', '', 'University Company']:
            self.assertIsNone(institution_type({'当前机构':name}))
        self.assertEqual(institution_type({'当前机构':'MIT','机构类型':'大学'}),'university')

    def test_bad_facets_cannot_cross_semantic_boundaries(self):
        for facet in [
            {'slot':'current_region','values':['美国'],'evidence':'英国'},
            {'slot':'current_institution','values':['英国'],'evidence':'英国'},
            {'slot':'institution_type','values':['university'],'evidence':'英国'},
            {'slot':'current_region','values':['英国'],'evidence':'not in question'},
            {'slot':'metric','field':'姓名','op':'gte','values':['10'],'evidence':'英国'},
            {'slot':'made_up','values':['英国'],'evidence':'英国'},
        ]:
            with self.subTest(facet=facet), self.assertRaises(ValueError):
                self.compile({'facets':[facet]}, '英国')

    def test_typed_history_relation_retains_source_evidence(self):
        plan=self.compile({'facets':[{'slot':'employment_history','values':['Example Lab'],'evidence':'曾任Example Lab'}]},'曾任Example Lab')
        self.assertEqual(bind_relations(plan,'曾任Example Lab').search.predicates[0].fields,['工作经历'])

    def test_country_replacement_and_explicit_basis_change_preserve_other_slots(self):
        for topic in ['AI4S','arbitrary-Zeta','蛋白质设计']:
            previous=self.compile({'facets':[{'slot':'topic','values':[topic],'evidence':topic}], 'sort_by':'OpenAlex h-index'},topic)
            for question in ['英国院校的人才有么','美国院校的呢','按所在地筛选','英国人才']:
                current=self.compile(local_geo_intent(question,previous.model_dump()),question,previous)
                previous=inherit_plan(current,previous.model_dump(),question,
                    reviewer=lambda _:self.fail('Grounded same-slot replacement must not invoke model review'))
                self.assertEqual(previous.sort_by,'OpenAlex h-index')
                self.assertEqual([p.values for p in previous.search.predicates if p.slot=='topic'],[[topic]])
            self.assertEqual([p.values for p in previous.search.predicates if p.slot=='current_region'],[['英国']])
            self.assertFalse(any(p.slot=='institution_country' for p in previous.search.predicates))
            self.assertTrue(any(p.slot=='institution_type' for p in previous.search.predicates))

    def test_unrelated_deletion_is_not_approved_by_a_country_change(self):
        previous=self.compile({'facets':[{'slot':'topic','values':['AI4S'],'evidence':'AI4S'}]},'AI4S')
        current=self.compile({'facets':[{'slot':'current_region','values':['英国'],'evidence':'英国'}],
                              'remove':['topic'],'evidence':'英国'},'英国',previous)
        with self.assertRaises(ContextChangeUnresolved):
            inherit_plan(current,previous.model_dump(),'英国')

    def test_basis_change_replaces_old_location_instead_of_intersecting_countries(self):
        previous=self.compile(local_geo_intent('美国人才'),'美国人才')
        delta=self.compile(local_geo_intent('英国院校'),'英国院校',previous)
        previous=inherit_plan(delta,previous.model_dump(),'英国院校')
        delta=self.compile(local_geo_intent('按所在地筛选',previous.model_dump()),'按所在地筛选',previous)
        resolved=inherit_plan(delta,previous.model_dump(),'按所在地筛选')
        self.assertEqual([p.values for p in resolved.search.predicates if p.slot=='current_region'],[['英国']])
        self.assertFalse(any(p.slot=='institution_country' for p in resolved.search.predicates))


class SemanticApiTests(unittest.TestCase):
    setUp=workspace.WorkspaceTests.setUp
    tearDown=workspace.WorkspaceTests.tearDown
    base=workspace.WorkspaceTests.base

    def test_operation_only_model_outputs_work_on_json_and_streaming_endpoints(self):
        import json
        from app.schemas.usage import ChatResult, TokenUsage
        base=self.base();book=Workbook();sheet=book.active
        sheet.append(['姓名','领域','当前机构','所在国家／城市'])
        for row in [['A','alpha','Example University','美国'],['B','beta','Example University','英国'],['C','gamma','Other University','美国']]:
            sheet.append(row)
        output=io.BytesIO();book.save(output)
        self.client.post(f'/api/knowledge/bases/{base}/upload',files={'file':('people.xlsx',output.getvalue(),'application/octet-stream')})
        cases=[('一共多少人才',{'operation':'count'},'共 3 条'),
               ('一共有多少人才',{'operation':'count'},'共 3 条'),
               ('有多少个不同的当前机构',{'operation':'distinct_count','field':'当前机构'},'2 个不同'),
               ('按当前所在地国家统计人数',{'operation':'group_count','field':'所在国家／城市'},'2 个不同')]
        for endpoint in ['/api/knowledge/ask','/api/knowledge/ask/stream']:
            for question,plan,expected in cases:
                with self.subTest(endpoint=endpoint,question=question), patch.object(OpenAICompatibleProvider,'chat',
                     return_value=ChatResult(content=json.dumps(plan),usage=TokenUsage())):
                    response=self.client.post(endpoint,json={'question':question,'knowledge_base_id':base})
                    self.assertEqual(response.status_code,200,response.text)
                    self.assertIn(expected,response.text)

    def test_model_uses_typed_facets_and_receives_compact_schema(self):
        import json
        from app.schemas.usage import ChatResult, TokenUsage
        base=self.base();book=Workbook();sheet=book.active
        sheet.append(['姓名','领域','当前机构','所在国家／城市'])
        sheet.append(['A','AI4S','Example University','美国'])
        sheet.append(['B','other','Example University','美国'])
        output=io.BytesIO();book.save(output)
        self.client.post(f'/api/knowledge/bases/{base}/upload',files={'file':('people.xlsx',output.getvalue(),'application/octet-stream')})
        def model(config,messages,model,key):
            request=json.loads(messages[-1].content)
            self.assertIn('available_slots',request['schema'])
            self.assertNotIn('fields',request['schema'])
            return ChatResult(content=json.dumps({'facets':[
                {'slot':'current_region','values':['海外'],'evidence':'海外'},
                {'slot':'topic','values':['AI4S'],'evidence':'AI4S'},
            ]}),usage=TokenUsage())
        with patch.object(OpenAICompatibleProvider,'chat',side_effect=model) as chat, \
             patch('app.services.talent_fast_search.ready_index',return_value=(None,'warming')):
            response=self.client.post('/api/knowledge/ask',json={'question':'查找海外，从事AI4S领域的人才','knowledge_base_id':base})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual([r['fields']['姓名'] for r in response.json()['row_sources']],['A'])
        self.assertEqual(chat.call_count,1)

    def test_pending_country_survives_serialized_history_and_resumes_on_explicit_basis(self):
        base=self.base(); book=Workbook(); sheet=book.active
        sheet.append(['姓名','领域','当前机构','所在国家／城市','OpenAlex h-index'])
        for row in [
            ['UK academic','AI4S','Northbridge University','UK / London',20],
            ['US academic','AI4S','Westbridge University','美国／波士顿',30],
            ['US company','AI4S','Example Company','美国',40],
            ['Unclassified','AI4S','MIT','美国',99],
            ['Different topic','other','Example University','美国',100],
        ]:sheet.append(row)
        output=io.BytesIO();book.save(output)
        response=self.client.post(f'/api/knowledge/bases/{base}/upload',files={'file':('roster.xlsx',output.getvalue(),'application/octet-stream')})
        self.assertEqual(response.status_code,201,response.text)
        history=[]
        with patch.object(OpenAICompatibleProvider,'chat',side_effect=AssertionError('No LLM on literal structured transitions')) as model, \
             patch('app.services.talent_fast_search.ready_index',return_value=(None,'warming')):
            def ask(question):
                result=self.client.post('/api/knowledge/ask',json={'question':question,'knowledge_base_id':base,'history':history})
                self.assertEqual(result.status_code,200,result.text)
                data=result.json()
                history.append({'question':question,'answer':data['answer'],'query_state':data['query_state']})
                return data
            self.assertEqual(len(ask('从事AI4S领域的人才')['row_sources']),4)
            for question in ['英国院校的人才有么','美国院校的呢']:
                pending=ask(question)
                self.assertEqual(pending['row_sources'],[])
                self.assertIn('缺少',pending['answer'])
                self.assertIn('这不是没有匹配人才',pending['answer'])
                self.assertIsNotNone(pending['query_state'])
            result=ask('按所在地筛选')
            self.assertEqual([r['fields']['姓名'] for r in result['row_sources']],['US academic'])
            result=ask('英国人才')
            self.assertEqual([r['fields']['姓名'] for r in result['row_sources']],['UK academic'])
            model.assert_not_called()
