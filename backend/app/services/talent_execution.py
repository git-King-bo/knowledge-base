"""Progressive record-level query execution, independent of recall/model budgets.

Recall determines evaluation order, never membership. A snapshot owns the complete
eligible queue, evaluated prefix and accepted evidence. Pagination consumes that
snapshot; it does not reinterpret the user's query or restart verification.
"""
from copy import deepcopy

from app.core.limits import MAX_MODEL_CALLS_PER_OPERATION
from app.core.security import usage_counter
from app.services.agent_trace import trace_note, trace_stage
from app.services.talent_evidence import verify_candidates
from app.services.talent_results import result_page, save_result
from app.services.talent_search import TalentConcept, TalentPlan, execute_plan, number_value


def record_key(group, row):
    return (group['source_id'], group['sheet'], row['excel_row'])


def start_search(question, plan, sheets, failures, planner, hybrid_search, scope, offset, page_size):
    # Literal/numeric predicates are the only early exclusions. All semantic
    # facts remain eligible even when a synonym or an embedding is unavailable.
    broad = plan.model_copy(update={'concepts': [], 'intent': 'filter'})
    results = execute_plan(broad, sheets, all_records=True, include_unranked=True)
    entries = [(i, row) for i, group in enumerate(results) for row in group.get('records', [])]
    retrieval = None
    if plan.evidence_conditions and not plan.sort_by and hybrid_search:
        recall_plan=plan
        if not plan.concepts:
            fields=list(dict.fromkeys(field for sheet in sheets for field in sheet.headers))[:12]
            recall_plan=plan.model_copy(update={'concepts':[TalentConcept(fields=fields,terms=[question])]})
        with trace_stage('人才记录级召回排序'):
            recalled, retrieval = hybrid_search(question, recall_plan, sheets)
        priority = {record_key(group, row): row.get('_hybrid_rank', n)
                    for n, (group, row) in enumerate(
                        (g, r) for g in recalled for r in g.get('records', []))}
        entries.sort(key=lambda item: priority.get(record_key(results[item[0]], item[1]), len(priority)))
    elif plan.evidence_conditions and not plan.sort_by:
        from app.services.talent_hybrid import bm25
        terms = ' '.join(term for concept in plan.concepts for term in concept.terms) or question
        scores = bm25(terms, ['\n'.join(row['fields'].values()) for _, row in entries])
        entries = [entry for _, entry in sorted(zip(scores, entries), key=lambda pair: pair[0], reverse=True)]
    if plan.sort_by:
        # Rank the entire eligible set BEFORE spending any verification budget.
        # Missing metrics come last and remain available as unranked matches.
        def metric(item):
            value = number_value(item[1]['fields'].get(plan.sort_by, ''))
            return (value is None, (-value if plan.descending else value) if value is not None else 0)
        entries.sort(key=metric)
    for order, (_, row) in enumerate(entries):
        row['_search_order'] = order
    state = None
    verification = None
    if plan.evidence_conditions:
        state = {'queue': entries, 'cursor': 0, 'total': len(entries), 'unknown': 0,
                 'unverified': 0, 'rejected': 0, 'supported': 0, 'adjacent': 0}
        verification = {'candidates': 0, 'supported': 0, 'adjacent': 0, 'unknown': 0,
                        'unverified': 0, 'rejected': 0, 'related': [],
                        'conditions': plan.evidence_conditions}
        for group in results:
            if 'error' not in group:
                group['records'] = []
                group['matched_records'] = 0
    evidence = {'results': results, 'unreadable_files': failures, 'plan': plan.model_dump(),
                'verification': verification, 'retrieval': retrieval, '_execution': state,
                'max_returned_records': page_size, 'scope_note': '按记录核验；资料缺失与未处理不视为不匹配。'}
    return resume_search(evidence, question, planner, scope, offset, page_size)


def refresh_result(evidence):
    plan = TalentPlan.model_validate(evidence['plan'])
    state = evidence.get('_execution')
    entries = [(i, row) for i, group in enumerate(evidence['results']) for row in group.get('records', [])]
    entries.sort(key=lambda item: item[1].get('_search_order', 0))
    ranked = [(i, row) for i, row in entries
              if not plan.sort_by or number_value(row['fields'].get(plan.sort_by, '')) is not None]
    pending = state['total'] - state['cursor'] if state else 0
    total = len(entries)
    unranked = bool(plan.sort_by and total and not ranked)
    # Sorting is not a presence filter: keep matching records without a metric.
    ordered = ranked + [(i, row) for i, row in entries
                        if plan.sort_by and number_value(row['fields'].get(plan.sort_by, '')) is None]
    for group in evidence['results']:
        if 'error' in group:
            continue
        rows = group['records']
        group['matched_records'] = len(rows)
        group['rankable_records'] = sum(number_value(r['fields'].get(plan.sort_by, '')) is not None for r in rows) if plan.sort_by else None
        group['missing_sort_values'] = len(rows) - group['rankable_records'] if plan.sort_by else None
    complete = not pending
    uncertain = (state['unknown'] + state['unverified']) if state else 0
    incomplete_sources = bool(evidence['unreadable_files'] or any('error' in g for g in evidence['results']))
    # All not-yet-evaluated numeric candidates rank below this evaluated prefix.
    # Unknown/failed evaluations prevent a certified global top-N claim.
    adjacent = state['adjacent'] if state else 0
    ranking_proven = bool(plan.sort_by and not unranked and not uncertain and not adjacent and not incomplete_sources)
    result_limit = plan.result_limit
    limit_reached = result_limit is not None and len(ordered) >= result_limit
    if result_limit:
        ordered = ordered[:result_limit]
    evidence.update(matched=total, rankable=len(ranked) if plan.sort_by else None,
                    missing=total-len(ranked) if plan.sort_by else None, unranked=unranked,
                    result_order=[[evidence['results'][i]['source_id'], evidence['results'][i]['sheet'], row['excel_row']]
                                  for i, row in ordered],
                    ranking_scope=('verified_prefix' if ranking_proven else 'matched_results') if plan.sort_by else None,
                    coverage={'eligible': state['total'] if state else total,
                              'evaluated': state['cursor'] if state else total,
                              'pending': pending, 'unknown': uncertain, 'adjacent': adjacent,
                              'complete': complete and not incomplete_sources,
                              'ranking_proven': ranking_proven,
                              'result_limit_reached': limit_reached},
                    status='partial' if pending or uncertain or incomplete_sources else 'complete')
    return pending and not limit_reached


def resume_search(evidence, question, planner, scope, offset, page_size):
    plan = TalentPlan.model_validate(evidence['plan'])
    state = evidence.get('_execution')
    more = refresh_result(evidence)
    # Existing verified pages are free; only exhaust model budget when the next
    # page needs more accepted rows. Every call preserves the earlier results.
    initial_slots = max(0, MAX_MODEL_CALLS_PER_OPERATION - (usage_counter.get() or {}).get('dispatched', 0))
    calls = 0
    while state and more and (plan.intent == 'aggregate' or len(evidence['result_order']) < offset + page_size):
        slots = min(initial_slots-calls, max(0, MAX_MODEL_CALLS_PER_OPERATION - (usage_counter.get() or {}).get('dispatched', 0)))
        if slots <= 0:
            break
        width = slots * 6 if (slots >= 2 and callable(getattr(planner, 'batch', None))
                       and (plan.result_limit is None or plan.result_limit > 6)) else 6
        window = state['queue'][state['cursor']:state['cursor'] + width]
        if window:
            batches = []
            for index, row in window:
                group = evidence['results'][index]
                batches.append({'source_id': group['source_id'], 'file': group['file'], 'sheet': group['sheet'],
                                'records': [deepcopy(row)], 'matched_records': 1})
            with trace_stage('渐进人才条件核验'):
                stats = verify_candidates(question, plan, batches, planner, max_calls=slots)
            calls += stats['model_calls']
            for (index, _), group in zip(window, batches):
                evidence['results'][index]['records'].extend(group['records'])
            state['cursor'] += len(window)
            for key in ('supported', 'adjacent', 'unknown', 'unverified', 'rejected'):
                state[key] += stats.get(key, 0)
                evidence['verification'][key] = state[key]
            evidence['verification']['candidates'] = state['cursor']
            evidence['verification']['related'] = (evidence['verification']['related'] + stats.get('related', []))[:3]
            evidence['verification']['basis'] = '完整候选集合按优先顺序渐进核验，已确认结果与待处理记录分别保存。'
            more = refresh_result(evidence)
    evidence['can_continue'] = bool(more)
    if plan.intent == 'aggregate':
        from collections import Counter
        rows = [row for group in evidence['results'] for row in group.get('records', [])]
        values = Counter(row['fields'].get(plan.field, '').strip() for row in rows)
        empty = values.pop('', 0)
        evidence['aggregate'] = {
            'operation': plan.operation, 'field': plan.field, 'records': len(rows),
            'distinct': len(values), 'empty': empty, 'groups': dict(sorted(values.items())),
            'sources': [{'file': group['file'], 'sheet': group['sheet'],
                         'scanned_records': group.get('scanned_records', 0)} for group in evidence['results']],
            'basis': '只统计原文确认满足条件的记录；空值不计类别，多值不拆分，不按姓名去重。',
        }
        evidence['result_order'] = []
    evidence['snapshot_id'] = save_result(scope, question, evidence['plan'], evidence)
    trace_note('人才查询执行进度', status=evidence['status'], **evidence['coverage'])
    # Only verified public evidence is serialized. The pending queue stays on
    # the server and is never accepted back from a client.
    public = deepcopy(evidence)
    public.pop('_execution', None)
    return result_page(public, offset, page_size)
