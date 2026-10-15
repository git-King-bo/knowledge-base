import io
import unittest
from unittest.mock import patch
from openpyxl import Workbook
from sqlalchemy import select

import test_workspace as workspace
from app.ai.providers.openai_compatible import OpenAICompatibleProvider
from app.db.models import AgentTraceModel
from app.db.models import AIProviderModel
from app.core.config import settings
from app.schemas.usage import ChatResult,TokenUsage
from app.services.talent_search import TalentSheet
from app.services.talent_structured_router import compile_structured, sort_action


class RouterContractTests(unittest.TestCase):
    def test_unknown_text_and_ambiguous_metrics_never_get_partially_executed(self):
        sheet=TalentSheet('s','f','t',['姓名','当前机构','所在国家／城市','OpenAlex h-index'],[
            {'fields':{'姓名':'A','当前机构':'Example Lab','所在国家／城市':'美国'}}])
        for q in ['查找海外人才但排除美国','查找海外人才并且研究alpha','在Example Lab和Other Lab工作过的有哪些',
                  '按OpenAlex h-index排序只看女性','h-index排序','查找大学人才']:
            self.assertIsNone(compile_structured(q,[sheet]),q)
        self.assertIsNone(sort_action('按h-index排序',['Google Scholar h-index','OpenAlex h-index']))

    def test_unknown_geography_requires_semantic_planning(self):
        sheet=TalentSheet('s','f','t',['姓名','所在国家／城市'],[
            {'fields':{'姓名':'A','所在国家／城市':'美国'}},
            {'fields':{'姓名':'B','所在国家／城市':'某地'}}])
        self.assertIsNone(compile_structured('帮我查找海外人才',[sheet]))

    def test_single_topic_and_institution_topic_compile_generically(self):
        sheet=TalentSheet('s','f','t',['姓名','当前机构','研究方向','代表成果'],[
            {'fields':{'姓名':'A','当前机构':'Northbridge University School of Science','研究方向':'alpha'}},
            {'fields':{'姓名':'B','当前机构':'Other University','代表成果':'alpha'}}])
        topic=compile_structured('查找alpha领域人才',[sheet])
        self.assertEqual(topic.search.predicates[0].values,['alpha'])
        combined=compile_structured('查找Northbridge University alpha领域人才',[sheet])
        self.assertEqual([p.kind for p in combined.search.predicates],['metadata','topic'])
        self.assertEqual(combined.search.predicates[0].values,['Northbridge University'])
        current=compile_structured('当前任职Northbridge University的人才',[sheet])
        self.assertEqual(current.search.predicates[0].relation,'current_affiliation')
        for q in ['查找alpha和beta领域人才','查找不含alpha领域人才']:
            self.assertIsNone(compile_structured(q,[sheet]))


class StructuredApiTests(unittest.TestCase):
    setUp=workspace.WorkspaceTests.setUp
    tearDown=workspace.WorkspaceTests.tearDown
    base=workspace.WorkspaceTests.base

    def roster(self):
        base=self.base();book=Workbook();sheet=book.active
        sheet.append(['姓名','当前机构','工作经历','所在国家／城市','OpenAlex h-index','上次自动更新时间','详细个人简介'])
        for row in [
            ['A','Example Lab','','美国','5','2026-01-01',''],
            ['B','New Lab','曾任Example Lab研究员','英国','','2026-08-01',''],
            ['C','Example Lab','','中国','100','2026-01-01',''],
            ['D','Other Lab','','美国','9','2026-01-01','迎来Example Lab时刻'],
            ['E','Other Lab','','美国','','2025-01-01',''],
            ['F','Example Lab','','','20','','']]:sheet.append(row)
        output=io.BytesIO();book.save(output)
        response=self.client.post(f'/api/knowledge/bases/{base}/upload',files={'file':('people.xlsx',output.getvalue(),'application/octet-stream')})
        self.assertEqual(response.status_code,201,response.text)
        return base

    def test_filter_sort_employment_followup_need_no_models_and_keep_scope(self):
        base=self.roster();history=[]
        with patch.object(OpenAICompatibleProvider,'chat',side_effect=AssertionError('No LLM on structured lane')) as model:
            def ask(question):
                response=self.client.post('/api/knowledge/ask',json={'question':question,'knowledge_base_id':base,'history':history})
                self.assertEqual(response.status_code,200,response.text)
                data=response.json();history.append({'question':question,'answer':data['answer'],'query_state':data['query_state']})
                return data
            first=ask('帮我查找海外人才')
            self.assertEqual({r['fields']['姓名'] for r in first['row_sources']},{'A','B','D','E'})
            ranked=ask('按照 OpenAlex h-index排序')
            self.assertEqual([r['fields']['姓名'] for r in ranked['row_sources']],['D','A','B','E'])
            self.assertIn('更新时间',ranked['answer'])
            narrowed=ask('在 Example Lab工作过的有哪些')
            self.assertEqual([r['fields']['姓名'] for r in narrowed['row_sources']],['A','B'])
            self.assertIn('当前所在地在海外',narrowed['answer'])
            self.assertIn('工作经历',narrowed['row_sources'][1]['fields']['检索依据'])
            model.assert_not_called()

    def test_planner_timeout_is_failure_not_successful_clarification(self):
        base=self.roster()
        for endpoint in ('/api/knowledge/ask','/api/knowledge/ask/stream'):
            with patch.object(OpenAICompatibleProvider,'chat',side_effect=TimeoutError('upstream timeout')):
                response=self.client.post(endpoint,json={'question':'查找具有跨学科创业潜力的人才','knowledge_base_id':base})
            self.assertEqual(response.status_code,503,response.text)
            trace=self.db.scalar(select(AgentTraceModel).order_by(AgentTraceModel.created_at.desc()).limit(1))
            self.assertEqual(trace.status,'error')
            self.assertIn('规划模型',trace.error)

    def test_missing_fixed_planner_does_not_break_structured_lane(self):
        base=self.roster()
        with patch.object(settings,'talent_planner_provider_id','deleted-provider'), \
             patch.object(OpenAICompatibleProvider,'chat',side_effect=AssertionError('local query must not call a model')):
            local=self.client.post('/api/knowledge/ask',json={'question':'查找海外人才','knowledge_base_id':base})
            semantic=self.client.post('/api/knowledge/ask',json={
                'question':'查找具有跨学科创业潜力的人才','knowledge_base_id':base})
        self.assertEqual(local.status_code,200,local.text)
        self.assertEqual(semantic.status_code,503,semantic.text)
        self.assertIn('规划模型',semantic.json()['detail'])

    def test_user_answer_model_does_not_change_fixed_talent_planner(self):
        base=self.roster()
        self.db.add(AIProviderModel(id='alternate',name='Alternate',provider='openai-compatible',
            base_url='https://alternate.invalid/v1',default_model='alternate-model',api_key_hint='',is_default=False))
        self.db.commit();seen=[]
        def plan(config,messages,model,key):
            from app.ai.base import json_max_output_tokens, json_output_requested
            seen.append((config.id,model,json_output_requested.get(),json_max_output_tokens.get()))
            return ChatResult(content='{"search":{"predicates":[{"condition":"subjective potential","kind":"unresolved"}]}}',usage=TokenUsage())
        with patch.object(settings,'talent_planner_provider_id','fixture'),patch.object(settings,'talent_planner_model','fixed-planner'), \
             patch.object(OpenAICompatibleProvider,'chat',side_effect=plan):
            response=self.client.post('/api/knowledge/ask',json={'question':'find people with subjective potential',
                'knowledge_base_id':base,'provider_id':'alternate','model':'alternate-model'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(seen,[('fixture','fixed-planner',True,settings.structured_model_max_output_tokens)])
        self.assertEqual(response.json()['model'],'alternate-model')
