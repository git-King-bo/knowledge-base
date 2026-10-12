"""Offline diagnostic probes; no model calls or application/database mutations.

Run from the repository root:
  backend/.venv/bin/python backend/scripts/audit_talent_retrieval.py

Plans and verifier responses are controlled fixtures, not measurements of a live
model's language understanding. The local SQLite snapshot is opened read-only.
"""
import json
import os
from pathlib import Path
import sqlite3
import sys
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
os.environ['APP_DATABASE_MODE'] = 'sqlite'
os.environ['DATABASE_URL'] = 'sqlite://'
os.environ['APP_SQLITE_FALLBACK_URL'] = 'sqlite://'

from app.core.security import usage_counter
from app.services.talent_search import (
    TalentConcept, TalentFilter, TalentPlan, TalentSheet, execute_plan,
    protect_text_filters, rule_plan, talent_context, validate_plan,
)
from app.services.talent_hybrid import hybrid_talents


def sheet(count):
    fields = ['姓名', '当前机构', '详细个人简介', '教育经历', 'OpenAlex h-index', '创业／项目经历']
    return TalentSheet('fixture', 'synthetic.xlsx', 'Sheet1', fields, [
        {'row': i + 2, 'fields': {
            '姓名': f'人才{i + 1}', '当前机构': '美国示例大学',
            '详细个人简介': '研究机器人', '教育经历': '美国示例大学博士',
            'OpenAlex h-index': str(i + 1), '创业／项目经历': '创办机器人公司',
        }} for i in range(count)
    ])


def run_query(data, question, plan, dispatched=1, hybrid=False):
    calls = []

    def planner(payload):
        if payload.get('phase') != 'verify_candidates':
            return plan.model_dump_json()
        calls.append(len(payload['candidates']))
        return json.dumps({'decisions': [
            {'id': item['id'], 'checks': [
                {'status': 'supported', 'refs': [item['passages'][0]['id']]}
                for _ in payload['conditions']
            ]} for item in payload['candidates']
        ]})

    counter = usage_counter.set({'dispatched': dispatched})
    try:
        with patch('app.services.talent_search.read_talent_sheets', return_value=([data], [])), \
             patch('app.services.talent_hybrid.EmbeddingClient') as embedding:
            embedding.return_value.enabled = False
            result = talent_context(question, [], planner, max_results=5,
                hybrid_search=(lambda q, p, s: hybrid_talents(Mock(), 'fixture', q, p, s)) if hybrid else None)
        return (json.loads(result) if result.startswith('{') else result), calls
    finally:
        usage_counter.reset(counter)


def main():
    report = {'scope': '本地代码、受控计划与核验响应、只读SQLite快照；未调用线上模型或读取线上日志'}
    plan = TalentPlan(sort_by='OpenAlex h-index', evidence_conditions=['当前任职于中国以外的大学'])
    capacity = []
    for spent, count in [(1, 18), (1, 19), (2, 12), (2, 13)]:
        result, calls = run_query(sheet(count), '查找海外 openlex h-index最高的人才', plan, spent)
        failed = isinstance(result, str)
        assert not failed
        capacity.append({'already_dispatched': spent, 'candidates': count,
                         'verification_batches': calls, 'coverage': result['coverage'], 'outcome': '返回已核验结果及进度'})
    report['capacity_boundary'] = capacity

    validate_plan(TalentPlan(evidence_conditions=['当前在海外任职']), [sheet(1)])
    report['semantic_condition_only'] = 'accepted'

    ranked_plan = TalentPlan(sort_by='OpenAlex h-index', result_limit=1,
        concepts=[TalentConcept(fields=['详细个人简介'], terms=['机器人'])],
        evidence_conditions=['研究机器人'])
    result, _ = run_query(sheet(25), '查找研究机器人的人才，按OpenAlex h-index最高排序', ranked_plan, hybrid=True)
    returned = [int(r['fields']['OpenAlex h-index']) for g in result['results'] for r in g['records']]
    assert max(returned) == 25
    report['rank_after_candidate_cutoff'] = {
        'synthetic_true_max': 25, 'returned_max': max(returned),
        'retrieval': result['retrieval'], 'ranking_scope': result['ranking_scope'],
        'pagination': result['pagination'],
    }

    projected = execute_plan(plan, [sheet(1)], all_records=True, include_unranked=True)
    report['project_evidence_projection'] = {
        'source_has_project': '创业／项目经历' in sheet(1).rows[0]['fields'],
        'verifier_input_has_project': '创业／项目经历' in projected[0]['records'][0]['fields'],
    }

    alias_data = sheet(2)
    alias_data.rows[0]['fields']['当前机构'] = '清华大学'
    alias_data.rows[1]['fields']['当前机构'] = 'Tsinghua University'
    institution_plan = protect_text_filters(
        TalentPlan(filters=[TalentFilter(field='当前机构', value='清华大学')]),
        '查找清华大学的人才', [alias_data])
    alias_result, _ = run_query(alias_data, '查找清华大学的人才', institution_plan)
    report['institution_alias'] = {
        'fixture_institution_values': [r['fields']['当前机构'] for r in alias_data.rows],
        'eligible_for_semantic_verification': alias_result['coverage']['eligible'],
        'verification_conditions': institution_plan.evidence_conditions,
    }

    db_path = ROOT / 'backend/knowledge_base.db'
    if db_path.exists():
        db = sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True)
        try:
            counts = {table: db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                      for table in ['talents', 'knowledge_chunks', 'knowledge_chunk_embeddings', 'chunk_talents']}
            report['local_snapshot_counts'] = counts
            grouped = {}
            for source, tab, row, raw in db.execute('SELECT source_id,sheet_name,source_row,raw_data_json FROM talents'):
                grouped.setdefault((source, tab), []).append({'row': row, 'fields': {
                    k: '' if v is None else str(v) for k, v in json.loads(raw).items()}})
            local = []
            for index, ((source, tab), rows) in enumerate(grouped.items(), 1):
                data = TalentSheet(source, f'local-sheet-{index}', tab,
                    list(dict.fromkeys(k for r in rows for k in r['fields'])), rows)
                question = '查找海外 openlex h-index最高的人才'
                result, calls = run_query(data, question, plan)
                assert isinstance(result, dict)
                local.append({'sheet': index, 'rows': len(rows),
                    'rule_plan': rule_plan(question, [data]),
                    'controlled_plan': plan.model_dump(), 'verification_batches': calls,
                    'result': {'matched': result['matched'], 'status': result['status'], 'coverage': result['coverage']}})
            report['local_rows_controlled_plan_reproduction'] = local
        finally:
            db.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
