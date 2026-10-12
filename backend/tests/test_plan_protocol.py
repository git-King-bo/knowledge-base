import json
import unittest
from app.services.talent_search import TalentPlan, parse_model_plan


class PlanProtocolTests(unittest.TestCase):
    def test_unambiguous_wrappers_preserve_all_conditions(self):
        plan = TalentPlan(evidence_conditions=['region constraint'], topic_condition='domain A or domain B', sort_by='score').model_dump()
        for wrapper in (lambda x:x, lambda x:[x]):
            for context in ({}, None):
                with self.subTest(wrapper=wrapper, context=context):
                    raw = json.dumps(wrapper({**plan, 'context_update':context}))
                    parsed = parse_model_plan('```json\n'+raw+'\n```')
                    self.assertEqual(parsed.evidence_conditions, plan['evidence_conditions'])
                    self.assertEqual(parsed.topic_condition, plan['topic_condition'])
                    self.assertEqual(parsed.sort_by, 'score')
                    self.assertFalse(parsed.context_update.reset)

    def test_ambiguous_or_invalid_payloads_are_never_silently_accepted(self):
        plan = TalentPlan(match_all=True).model_dump()
        bad = [json.dumps([plan, plan]), '[]', 'null', '{"intent":"filter","intent":"document"}',
               json.dumps({**plan,'unknown_key':1}), json.dumps({**plan,'context_update':[]}),
               json.dumps({**plan,'filters':None})]
        for raw in bad:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_model_plan(raw)
