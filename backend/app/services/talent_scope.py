"""Resolve result-set references only from an access/version-checked server snapshot."""
import json
from app.services.talent_context_update import ContextChangeUnresolved


def subject_scope(plan,planner):
    mode=plan.result_scope
    if mode=='all_matches' and plan.document_previous_results:mode='previous_results'  # old persisted plans
    if mode=='all_matches':return None
    previous=getattr(planner,'previous_snapshot',None)
    if not isinstance(previous,dict) or not previous:raise ContextChangeUnresolved('上一批结果已过期或资料已变化，请重新检索；不会自动扩大到全库。',plan=plan)
    if not plan.scope_explicit and '_scope_keys' in previous:
        return {tuple(k) for k in previous['_scope_keys']}
    if mode=='previous_page':
        keys=getattr(planner,'previous_page_keys',None)
        if not keys:raise ContextChangeUnresolved('上一轮没有展示可引用的人员名单，请先列出人员，再限定到本页。',plan=plan)
    else:keys=previous.get('result_order') or previous.get('_count_keys',[])
    return {tuple(k) for k in keys}


def reused_semantic_keys(plan,planner):
    previous=getattr(planner,'previous_snapshot',None)
    if not isinstance(previous,dict) or not previous:return set()
    def topics(data):
        return sorted(json.dumps({k:p.get(k) for k in ('kind','fields','op','values','related_values')},sort_keys=True,ensure_ascii=False)
                      for p in (data.get('search') or {}).get('predicates',[]) if p['kind']=='topic')
    if topics(plan.model_dump())!=topics(previous['plan']):return set()
    return {tuple(k) for k in previous.get('_semantic_verified_keys',[])}
