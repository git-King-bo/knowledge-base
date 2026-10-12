import unittest
from app.services.talent_search import TalentPlan,ContextUpdate,TalentFilter,validate_plan,TalentSheet
from app.services.talent_context_update import inherit_plan as apply_plan

# These tests validate the executor contract, not natural-language understanding.
def inherit_plan(*args, **kwargs):
    kwargs.setdefault("reviewer", lambda payload: '{"verdict":"supported"}')
    return apply_plan(*args, **kwargs)

class TalentContextUpdateTests(unittest.TestCase):
    def setUp(self):
        self.previous=TalentPlan(evidence_conditions=['当前所在地在中国以外（海外）'],sort_by='OpenAlex h-index',descending=True)

    def test_new_domain_does_not_drop_geography_or_sort(self):
        for topic in ['蛋白质领域','机器人领域','材料领域']:
            with self.subTest(topic=topic):
                result=inherit_plan(TalentPlan(topic_condition=topic),self.previous.model_dump(),'查找'+topic+'人才')
                self.assertEqual(result.evidence_conditions,self.previous.evidence_conditions)
                self.assertEqual(result.topic_condition,topic)
                self.assertEqual(result.sort_by,'OpenAlex h-index')
                self.assertTrue(result.descending)

    def test_replace_geography_is_explicit_and_does_not_clear_topic_or_sort(self):
        previous=self.previous.model_copy(update={'topic_condition':'研究领域','evidence_conditions':self.previous.evidence_conditions+['研究领域']})
        result=inherit_plan(TalentPlan(evidence_conditions=['当前在国内'],context_update=ContextUpdate(remove_conditions=[0],evidence='改为国内')),
                            previous.model_dump(),'改为国内')
        self.assertEqual(result.evidence_conditions,['当前在国内'])
        self.assertEqual(result.topic_condition,'研究领域')
        self.assertEqual(result.sort_by,'OpenAlex h-index')

    def test_new_topic_replaces_old_topic_but_preserves_other_dimensions(self):
        previous=self.previous.model_copy(update={'topic_condition':'旧方向','evidence_conditions':self.previous.evidence_conditions+['旧方向']})
        result=inherit_plan(TalentPlan(topic_condition='新方向',context_update=ContextUpdate(topic_action='replace',evidence='换成新方向')),previous.model_dump(),'换成新方向')
        self.assertEqual(result.evidence_conditions,self.previous.evidence_conditions)
        self.assertEqual(result.topic_condition,'新方向')

    def test_reset_requires_explicit_current_utterance(self):
        for evidence,question in [('重新搜索','查找领域人才'),('','查找领域人才')]:
            with self.assertRaises(ValueError):
                inherit_plan(TalentPlan(topic_condition='新方向',context_update=ContextUpdate(reset=True,evidence=evidence)),self.previous.model_dump(),question)
        result=inherit_plan(TalentPlan(topic_condition='新方向',context_update=ContextUpdate(reset=True,evidence='重新搜索')),
                            self.previous.model_dump(),'重新搜索新方向，不沿用之前条件')
        self.assertEqual(result.evidence_conditions,[])
        self.assertIsNone(result.sort_by)

    def test_cancel_sort_keeps_filter_and_reset_directives_are_consumed(self):
        result=inherit_plan(TalentPlan(context_update=ContextUpdate(clear_sort=True,evidence='取消排序')),self.previous.model_dump(),'取消排序')
        self.assertIsNone(result.sort_by)
        self.assertEqual(result.evidence_conditions,self.previous.evidence_conditions)
        self.assertEqual(result.context_update,ContextUpdate())

    def test_invalid_removal_index_fails_closed(self):
        with self.assertRaises(ValueError):
            inherit_plan(TalentPlan(context_update=ContextUpdate(remove_conditions=[7],evidence='取消条件')),
                         self.previous.model_dump(),'取消条件')

    def test_executor_repairs_omitted_context_before_verification(self):
        import json
        from unittest.mock import patch
        from app.services.talent_search import talent_context
        sheet=TalentSheet('source','人才.xlsx','人才',['姓名','OpenAlex h-index'],[
            {'row':2,'fields':{'姓名':'人员甲','OpenAlex h-index':'30'}}])
        conditions=[]
        def planner(payload):
            if payload.get('phase')!='verify_candidates':
                # Reproduce the actual faulty model response: only the new topic.
                return '{"intent":"filter","topic_condition":"蛋白质领域"}'
            conditions.extend(payload['conditions'])
            return json.dumps({'decisions':[{'id':r['id'],'checks':[{'status':'supported','refs':[0]} for _ in payload['conditions']]}
                                            for r in payload['candidates']]})
        planner.previous_plan=self.previous.model_dump()
        planner.requires_context=True
        planner.original_question='查找蛋白质领域人才'
        with patch('app.services.talent_search.read_talent_sheets',return_value=([sheet],[])):
            result=json.loads(talent_context(planner.original_question,[],planner))
        self.assertEqual(conditions,['当前所在地在中国以外（海外）','蛋白质领域'])
        self.assertEqual(result['plan']['sort_by'],'OpenAlex h-index')

    def test_count_inherits_membership_but_not_ranking_or_top_n(self):
        previous=self.previous.model_copy(update={'result_limit':10})
        result=inherit_plan(TalentPlan(intent='aggregate',operation='count'),previous.model_dump(),'这些人才有多少')
        self.assertEqual(result.evidence_conditions,self.previous.evidence_conditions)
        self.assertIsNone(result.sort_by)
        self.assertIsNone(result.result_limit)

    def test_explicitly_removing_last_condition_allows_all_records(self):
        previous=TalentPlan(evidence_conditions=['区域限制'])
        result=inherit_plan(TalentPlan(context_update=ContextUpdate(remove_conditions=[0],evidence='取消区域限制')),
                            previous.model_dump(),'取消区域限制')
        self.assertTrue(result.match_all)
        self.assertEqual(result.evidence_conditions,[])

    def test_generated_identifiers_obey_the_same_merge_invariants(self):
        """Opaque labels exercise execution, independently of any language or domain vocabulary."""
        import random
        import string
        rng=random.Random(47213)
        for case in range(120):
            labels=[''.join(rng.choices(string.ascii_letters,k=16)) for _ in range(8)]
            previous=TalentPlan(evidence_conditions=labels[:3],topic_condition=labels[3],sort_by=labels[4],descending=bool(case%2))
            before=previous.model_dump()
            question=labels[7]  # Contains no required command word.
            with self.subTest(case=case):
                added=inherit_plan(TalentPlan(evidence_conditions=[labels[5]]),before,question)
                self.assertEqual(added.evidence_conditions,labels[:3]+[labels[5]])
                self.assertEqual(added.sort_by,labels[4])
                self.assertEqual(added.descending,previous.descending)
                removed=inherit_plan(TalentPlan(context_update=ContextUpdate(remove_conditions=[case%3],evidence=question)),before,question)
                self.assertEqual(removed.evidence_conditions,[v for i,v in enumerate(labels[:3]) if i!=case%3])
                both=inherit_plan(TalentPlan(topic_condition=labels[6]),before,question)
                self.assertIn(labels[3],both.evidence_conditions)
                self.assertEqual(both.topic_condition,labels[6])
                reset=inherit_plan(TalentPlan(topic_condition=labels[6],context_update=ContextUpdate(reset=True,evidence=question)),before,question)
                self.assertEqual(reset.evidence_conditions,[])
                self.assertIsNone(reset.sort_by)
                self.assertEqual(previous.model_dump(),before)

    def test_destructive_changes_require_semantic_review_not_keyword_presence(self):
        from app.services.talent_context_update import ContextChangeUnresolved
        question='这个条件留着没有意义'
        delta=TalentPlan(context_update=ContextUpdate(remove_conditions=[0],evidence=question))
        for reviewer in (None, lambda p:'not json', lambda p:'{"verdict":"ambiguous","message":"具体指哪个条件？"}',
                         lambda p:'{"verdict":"unsupported","message":"需要保留原条件吗？"}'):
            with self.subTest(reviewer=reviewer),self.assertRaises(ContextChangeUnresolved):
                apply_plan(delta,self.previous.model_dump(),question,reviewer=reviewer)
        # A matching quote alone is insufficient, even if it contains an old trigger word.
        delta.context_update.evidence='重新'
        with self.assertRaises(ContextChangeUnresolved):
            apply_plan(delta,self.previous.model_dump(),'重新核对，筛选要求保持原样',
                       reviewer=lambda p:'{"verdict":"unsupported"}')

    def test_reviewer_sees_effective_plan_and_reset_discards_unattributed_sort(self):
        question='依据本次要求执行'
        seen=[]
        def review(payload):
            seen.append(payload)
            return '{"verdict":"supported"}'
        delta=TalentPlan(evidence_conditions=['新增条件'],context_update=ContextUpdate(remove_conditions=[0],evidence=question))
        apply_plan(delta,self.previous.model_dump(),question,reviewer=review)
        self.assertEqual(seen[0]['after']['conditions'],['新增条件'])
        self.assertEqual(seen[0]['after']['sort']['field'],self.previous.sort_by)
        previous=TalentPlan(evidence_conditions=[str(i) for i in range(5)],sort_by='old_metric')
        reset=TalentPlan(evidence_conditions=[str(i) for i in range(5,10)],sort_by='old_metric',
                         context_update=ContextUpdate(reset=True,evidence=question))
        result=apply_plan(reset,previous.model_dump(),question,reviewer=review)
        self.assertEqual(result.evidence_conditions,[str(i) for i in range(5,10)])
        self.assertIsNone(result.sort_by)
        reset.context_update.assignments={'sort_by':question}
        self.assertEqual(apply_plan(reset,previous.model_dump(),question,reviewer=review).sort_by,'old_metric')
