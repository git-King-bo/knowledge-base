import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from app.core.config import settings
from app.services.talent_search import TalentConcept,TalentFilter,TalentPlan,TalentSheet,validate_plan
from app.services.talent_hybrid import hybrid_talents
from app.services.talent_evidence import verify_candidates

class TalentHybridTests(unittest.TestCase):
    def setUp(self):
        fields=['姓名','当前机构','详细个人简介','教育经历','工作经历']
        self.sheet=TalentSheet('source','talents.xlsx','Sheet1',fields,[
            {'row':2,'talent_id':'a','fields':{'姓名':'甲','当前机构':'国内大学','详细个人简介':'托卡马克装置研究','教育经历':'中国大学博士'}},
            {'row':3,'talent_id':'b','fields':{'姓名':'乙','当前机构':'国内大学','详细个人简介':'magnetically confined hot charged particles','教育经历':'博士——美国加州大学圣地亚哥分校'}},
        ])
        self.plan=TalentPlan(concepts=[TalentConcept(fields=['详细个人简介'],terms=['托卡马克'])],
            evidence_conditions=['中国以外大学的学习或工作经历'],topic_condition='本人经历与托卡马克有关')
        self.plan=validate_plan(self.plan,[self.sheet])
        self.db=Mock()
        self.db.get_bind.return_value.url='test-hybrid'
        metadata=[
            (SimpleNamespace(id='chunk-b'),SimpleNamespace(embedding_model=settings.embedding_model,
                embedding_json='[0,1]',embedding_dim=2,created_at='unique'), 'b')]
        self.db.execute.side_effect=[Mock(all=Mock(return_value=metadata)),Mock(all=Mock(return_value=[('chunk-b','[0,1]')]))]

    def test_dense_only_person_is_recalled_without_keyword_and_retains_education(self):
        with patch('app.services.talent_hybrid.EmbeddingClient') as client:
            client.return_value.enabled=True
            client.return_value.embed_text.return_value=[0,1]
            results,meta=hybrid_talents(self.db,'base','找托卡马克海外经历人才',self.plan,[self.sheet])
        self.assertEqual(meta['dense_candidates'],1)
        self.assertEqual(meta['mode'],'BM25 + dense + RRF')
        self.assertEqual({r['fields']['姓名'] for r in results[0]['records']},{'甲','乙'})
        self.assertIn('美国',next(r for r in results[0]['records'] if r['fields']['姓名']=='乙')['fields']['教育经历'])
        self.assertEqual(client.return_value.embed_text.call_args.args[0],'托卡马克')

    def test_unavailable_embedding_is_explicit_not_claimed_as_semantic(self):
        with patch('app.services.talent_hybrid.EmbeddingClient') as client:
            client.return_value.embed_text.side_effect=RuntimeError('unavailable')
            results,meta=hybrid_talents(self.db,'base','托卡马克',self.plan,[self.sheet])
        self.assertIn('已降级',meta['mode'])
        self.assertEqual([r['fields']['姓名'] for r in results[0]['records']],['甲'])

    def test_topic_cannot_shift_onto_foreign_university_constraint(self):
        self.assertEqual(self.plan.topic_conditions,[1])
        def planner(payload):
            decisions=[]
            for item in payload['candidates']:
                refs={p['field']:p['id'] for p in item['passages']}
                abroad='美国' in item['fields'].get('教育经历','')
                decisions.append({'id':item['id'],'checks':[
                    {'status':'supported' if abroad else 'contradicted','refs':[refs['教育经历']]},
                    {'status':'related','refs':[refs['详细个人简介']]}]})
            return json.dumps({'decisions':decisions})
        results=[{'file':'talents.xlsx','sheet':'Sheet1','records':[
            {'excel_row':r['row'],'fields':dict(r['fields'])} for r in self.sheet.rows]}]
        stats=verify_candidates('有海外经历的相关人才',self.plan,results,planner)
        self.assertEqual(stats['adjacent'],1)
        self.assertEqual(stats['rejected'],1)
        self.assertEqual([r['fields']['姓名'] for r in results[0]['records']],['乙'])
        self.assertIn('美国加州',results[0]['records'][0]['fields']['条件核验依据'])
        self.assertIn('相近领域',results[0]['records'][0]['fields']['领域关联程度'])

    def test_compact_output_cannot_invent_evidence_reference(self):
        def planner(payload):
            return json.dumps({'decisions':[{'id':item['id'],'checks':[
                {'status':'supported','refs':[99999]},{'status':'supported','refs':[99999]}]}
                for item in payload['candidates']]})
        results=[{'file':'talents.xlsx','sheet':'Sheet1','records':[
            {'excel_row':r['row'],'fields':dict(r['fields'])} for r in self.sheet.rows]}]
        stats=verify_candidates('test',self.plan,results,planner)
        self.assertEqual(stats['supported'],0)
        self.assertEqual(stats['unverified'],2)

    def test_lexical_recall_respects_planned_education_fields(self):
        plan=validate_plan(TalentPlan(concepts=[TalentConcept(fields=['教育经历'],terms=['圣地亚哥'])],
            evidence_conditions=['有该大学教育经历']),[self.sheet])
        with patch('app.services.talent_hybrid.EmbeddingClient') as client:
            client.return_value.enabled=False
            results,_=hybrid_talents(self.db,'base','圣地亚哥大学教育经历',plan,[self.sheet])
        self.assertEqual([r['fields']['姓名'] for r in results[0]['records']],['乙'])
