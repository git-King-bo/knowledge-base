"""Render verified personnel results without asking a model to invent table rows."""
import html
import re

from app.schemas.knowledge import AskResponse, TalentQueryState
from app.services.talent_search import TalentPlan, number_value


class PreparedTalentAnswer(Exception):
    def __init__(self, response: AskResponse):
        self.response = response


def next_page_state(payload, history):
    if payload.continuation or not history or not re.fullmatch(
        r'\s*(继续|下一页|继续查看|继续列出|查看更多|接着列|后面的|还有呢)[。！!？?\s]*', payload.question
    ):
        return None
    state = history[-1].query_state
    if state is None or state.knowledge_base_id != payload.knowledge_base_id:
        return None
    # The client supplies conversation state, never evidence or authorization.
    # Plans are validated against current accessible sources and re-executed.
    TalentPlan.model_validate(state.plan)
    return state


def cell(value):
    return html.escape(str(value or '—')).replace('|', '&#124;').replace('\n', ' ').replace('\r', ' ').replace('`', '&#96;').replace('[', '&#91;').replace(']', '&#93;')


def render_talent_answer(evidence, row_sources):
    page = evidence['pagination']
    plan = evidence['plan']
    total = evidence['matched']
    labels = [f"{cell(item['field'])}：{cell(item['value'])}" for item in plan['filters']]
    # Expanded terms and verification instructions belong in traces, not the answer.
    parts = ['；'.join(labels)] if labels else []
    if evidence.get('ranking_scope')=='previous_results':
        parts.append('以下按上一轮已匹配的人才排序。')
    elif evidence.get('ranking_scope')=='matched_results':
        parts.append('以下对本次已匹配的人才排序，不代表全库排名。')
    verification = evidence.get('verification')
    if not total and verification:
        parts.append(f"跨字段召回 {verification['candidates']} 条候选，但现有原文尚不能确认有人同时满足全部条件。这不等于没有相关人才，也不代表已穷尽全库。")
    elif not total:
        parts.append('当前知识库中没有符合这些条件的人才记录。可以放宽机构或领域条件后再查询。')
    elif evidence['unranked']:
        parts.append(f"找到 {total} 条人才记录，均暂无 {cell(plan['sort_by'])}，以下展示基本信息，不做排名。")
    elif plan['sort_by']:
        parts.append(f"找到 {total} 条人才记录，其中 {evidence['rankable']} 条有 {cell(plan['sort_by'])}，按{'从高到低' if plan['descending'] else '从低到高'}排列；另有 {evidence['missing']} 条缺少该指标，不参与排名。")
    else:
        parts.append(f'找到 {total} 条人才记录。')
    if page['returned']:
        parts.append(f"本次展示第 {page['offset'] + 1}—{page['offset'] + page['returned']} 条。")
        columns = ['姓名', '当前机构', '当前职务', '领域']
        if verification:
            columns.append('领域关联程度')
            columns.append('条件核验依据')
        if plan['sort_by']:
            columns.append(plan['sort_by'])
        lines = ['| ' + ' | '.join(cell(column) for column in columns + ['来源']) + ' |', '| ' + ' | '.join(['---'] * (len(columns) + 1)) + ' |']
        rows = list(row_sources)
        if plan['sort_by'] and not evidence['unranked']:
            rows.sort(key=lambda row: number_value(row.fields.get(plan['sort_by'], '')), reverse=plan['descending'])
        for row in rows:
            fields = row.fields
            name = next((v for k, v in fields.items() if k.casefold() in {'姓名', '人员姓名', '员工姓名', 'name', 'full name'}), '')
            values = [cell(name if column == '姓名' else fields.get(column)) for column in columns]
            lines.append('| ' + ' | '.join(values + [f'(Record {row.index})']) + ' |')
        parts.append('\n'.join(lines))
    elif total:
        parts.append('当前查询结果已展示完，没有下一页。')
    if page['has_more']:
        parts.append('回复“继续”查看下一页。')
    elif page['returned']:
        parts.append('以上已展示完本次可列出的结果。')
    failed = evidence.get('unreadable_files', []) + [r['file'] for r in evidence['results'] if 'error' in r]
    if failed:
        parts.append('以下文件未能完整查询，以上数量仅覆盖成功查询的资料：' + '、'.join(cell(f) for f in failed))
    if verification:
        if verification.get('unverified'):
            parts.append(f"另有 {verification['unverified']} 条候选因模型响应异常或调用预算限制未完成核验；已保留上方核验成功的结果，不能将未完成的候选视为不匹配。")
        if verification.get('related'):
            lines=['待核验的相关候选（不计入匹配结果）：']
            for item in verification['related']:
                proof='已有资料：'+cell(item['supporting_evidence'])+'；' if item.get('supporting_evidence') else ''
                lines.append('- '+cell(item['name'])+'（'+cell(item['organization'])+'）：'+proof+
                    '尚未确认满足全部筛选条件。来源：'+cell(item['file'])+' / '+
                    cell(item['sheet'])+' 第 '+str(item['row'])+' 行。')
            parts.append('\n'.join(lines))
    return '\n\n'.join(parts)


def render_aggregate_answer(evidence):
    stats = evidence['aggregate']
    if stats['operation'] == 'count':
        answer = f"符合本次条件的人才记录共 {stats['records']} 条。"
    else:
        answer = f"符合本次条件的记录中，{cell(stats['field'])}共有 {stats['distinct']} 个不同的非空字段值。"
        answer += '\n\n| 字段值 | 记录数 |\n| --- | --- |\n'
        answer += '\n'.join(f"| {cell(value)} | {count} |" for value, count in stats['groups'].items())
        answer += f"\n\n另有 {stats['empty']} 条记录的该字段为空。"
    answer += '\n\n统计口径：' + stats['basis']
    answer += '\n\n统计来源：' + '；'.join(f"{cell(item['file'])} / {cell(item['sheet'])}（扫描 {item['scanned_records']} 条）" for item in stats['sources'])
    return answer


def prepare_response(payload, provider, query, evidence, rows):
    if evidence.get('result_order'):
        order={tuple(key):i for i,key in enumerate(evidence['result_order'])}
        rows=sorted(rows,key=lambda row:order.get((row.source_id,row.sheet,row.excel_row),len(order)))
        rows=[row.model_copy(update={'index':i}) for i,row in enumerate(rows,1)]
    if 'aggregate' in evidence:
        answer = render_aggregate_answer(evidence)
        return AskResponse(answer=answer, provider_id=provider.id, model=payload.model or provider.default_model,
                           sources=[], row_sources=[], retrieval_query=query)
    page = evidence['pagination']
    return AskResponse(answer=render_talent_answer(evidence, rows), provider_id=provider.id,
        model=payload.model or provider.default_model, sources=[], row_sources=rows, retrieval_query=query,
        query_state=TalentQueryState(knowledge_base_id=payload.knowledge_base_id, query=query,
            snapshot_id=evidence.get('snapshot_id'),
            plan=evidence['plan'], offset=page['offset'], page_size=page['page_size'],
            returned=page['returned'], has_more=page['has_more']))
