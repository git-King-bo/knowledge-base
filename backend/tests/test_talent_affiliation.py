import json
import unittest
from unittest.mock import patch

from app.services.talent_search import TalentPlan, TalentSheet, talent_context
from app.services.talent_search_schema import SearchPredicate, SearchSpec, bind_relations
from app.services.talent_fast_search import test_predicate


class AffiliationTests(unittest.TestCase):
    def predicate(self, **changes):
        return SearchPredicate(condition='institution', kind='metadata',
            fields=['当前机构', '教育经历', '工作经历'], values=['Northbridge University'], **changes)

    def test_current_default_never_matches_alumni_or_former_employment(self):
        for relation in (None, 'current_affiliation'):
            p=self.predicate(relation=relation)
            self.assertTrue(test_predicate({'当前机构':'Northbridge University, School of Science'}, p))
            self.assertFalse(test_predicate({'当前机构':'Other University',
                '教育经历':'Northbridge University PhD', '工作经历':'Northbridge University'}, p))
            self.assertIsNone(test_predicate({'教育经历':'Northbridge University PhD'}, p))

    def test_explicit_history_scopes_and_quote_validation(self):
        fields={'当前机构':'Other University','教育经历':'Northbridge University PhD','工作经历':'Third University'}
        for relation, expected in [('education',True),('employment_history',False),('any_affiliation',True)]:
            p=self.predicate(relation=relation, relation_evidence='alumni')
            plan=TalentPlan(search=SearchSpec(predicates=[p]))
            bound=bind_relations(plan, 'find alumni').search.predicates[0]
            self.assertEqual(test_predicate(fields,bound),expected)
            with self.assertRaises(ValueError):bind_relations(plan,'find current researchers')
        with self.assertRaises(ValueError):
            bind_relations(TalentPlan(search=SearchSpec(predicates=[self.predicate(relation='education')])), 'query')

    def test_institution_membership_preserves_departments_and_joint_appointments(self):
        p=self.predicate(relation='current_affiliation',op='equals_any')
        bound=bind_relations(TalentPlan(search=SearchSpec(predicates=[p])), 'find researchers').search.predicates[0]
        self.assertEqual(bound.op,'contains_any')
        for current in ('Northbridge University, School of Science','Institute A; Northbridge University'):
            self.assertTrue(test_predicate({'当前机构':current},bound))
        self.assertFalse(test_predicate({'当前机构':'Other University','工作经历':'Northbridge University'},bound))

    def test_real_compiler_intersects_current_institution_and_topic(self):
        sheet=TalentSheet('s','people.xlsx','S',['姓名','当前机构','教育经历','工作经历','研究方向'],[
            {'row':2,'fields':{'姓名':'current','当前机构':'Northbridge University','研究方向':'alpha'}},
            {'row':3,'fields':{'姓名':'alumnus','当前机构':'Other University','教育经历':'Northbridge University','研究方向':'alpha'}},
            {'row':4,'fields':{'姓名':'former','当前机构':'Other University','工作经历':'Northbridge University','研究方向':'alpha'}},
            {'row':5,'fields':{'姓名':'wrong-topic','当前机构':'Northbridge University','研究方向':'beta'}},
            {'row':6,'fields':{'姓名':'unknown-current','教育经历':'Northbridge University','研究方向':'alpha'}}])
        def planner(schema):
            return json.dumps({'search':{'predicates':[self.predicate().model_dump(),
                {'condition':'alpha','kind':'topic','fields':['研究方向'],'values':['alpha']}]}})
        planner.fast_search=True
        planner.search_db=None
        with patch('app.services.talent_search.read_talent_sheets', return_value=([sheet],[])):
            result=json.loads(talent_context('find researchers',[],planner))
        self.assertEqual(result['matched'],1)
        self.assertEqual(result['results'][0]['records'][0]['fields']['姓名'],'current')
        p=result['plan']['search']['predicates'][0]
        self.assertEqual(p['fields'],['当前机构'])
        self.assertEqual(p['relation'],'current_affiliation')
        self.assertEqual(result['coverage']['unknown'],1)

    def test_followup_keeps_bound_current_affiliation(self):
        from app.services.talent_context_update import inherit_plan
        p=self.predicate(relation='current_affiliation')
        previous=bind_relations(TalentPlan(evidence_conditions=['institution'],search=SearchSpec(predicates=[p])), 'find researchers')
        current=TalentPlan(topic_condition='alpha',evidence_conditions=['alpha'],search=SearchSpec(predicates=[
            SearchPredicate(condition='alpha',kind='topic',fields=['研究方向'],values=['alpha'])]))
        merged=inherit_plan(current,previous.model_dump(),'alpha researchers')
        saved=next(p for p in merged.search.predicates if p.condition=='institution')
        self.assertEqual(saved.fields,['当前机构'])
        self.assertEqual(saved.relation,'current_affiliation')
