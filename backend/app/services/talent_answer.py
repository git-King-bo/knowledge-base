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
    if evidence.get('search_mode') == 'hybrid':
        return render_search_answer(evidence, row_sources)
    page = evidence['pagination']
    plan = evidence['plan']
    total = evidence['matched']
    labels = [f"{cell(item['field'])}：{cell(item['value'])}" for item in plan['filters']]
    # Expanded terms and verification instructions belong in traces, not the answer.
    parts = ['；'.join(labels)] if labels else []
    coverage = evidence.get('coverage', {})
    if coverage and not coverage.get('complete'):
        parts.append(f"已核验 {coverage['evaluated']} / {coverage['eligible']} 条候选，以下为目前确认的结果。")
    if coverage.get('unknown'):
        parts.append(f"有 {coverage['unknown']} 条记录资料不足或未能完成核验，不能将其视为不匹配。")
    if evidence.get('ranking_scope')=='previous_results':
        parts.append('以下按上一轮已匹配的人才排序。')
    elif evidence.get('ranking_scope')=='matched_results':
        parts.append('以下对本次已匹配的人才排序，不代表全库排名。')
    elif evidence.get('ranking_scope')=='verified_prefix':
        parts.append('按完整候选范围的指标顺序核验后排列；尚未处理的有指标记录不会排在当前结果之前。')
    verification = evidence.get('verification')
    if not total and coverage.get('pending'):
        parts.append('目前已核验的记录中尚未确认匹配，仍有候选待处理。')
    elif not total and verification:
        parts.append(f"跨字段召回 {verification['candidates']} 条候选，但现有原文尚不能确认有人同时满足全部条件。这不等于没有相关人才，也不代表已穷尽全库。")
    elif not total:
        parts.append('当前知识库中没有符合这些条件的人才记录。可以放宽机构或领域条件后再查询。')
    elif evidence['unranked']:
        parts.append(f"找到 {total} 条人才记录，均暂无 {cell(plan['sort_by'])}，以下展示基本信息，不做排名。")
    elif plan['sort_by']:
        parts.append(f"找到 {total} 条人才记录，其中 {evidence['rankable']} 条有 {cell(plan['sort_by'])}，按{'从高到低' if plan['descending'] else '从低到高'}排列。")
        if evidence['missing']:
            parts.append(f"另有 {evidence['missing']} 条缺少该指标，仍保留展示，排在有指标的人才之后，并沿用原结果顺序。")
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
            def metric_key(row):
                value=number_value(row.fields.get(plan['sort_by'], ''))
                return (value is None, (-value if plan['descending'] else value) if value is not None else 0)
            rows.sort(key=metric_key)
        for row in rows:
            fields = row.fields
            name = next((v for k, v in fields.items() if k.casefold() in {'姓名', '人员姓名', '员工姓名', 'name', 'full name'}), '')
            values = [cell(name if column == '姓名' else fields.get(column)) for column in columns]
            lines.append('| ' + ' | '.join(values + [f'(Record {row.index})']) + ' |')
        parts.append('\n'.join(lines))
    elif total:
        parts.append('当前查询结果已展示完，没有下一页。')
    if not page['has_more'] and coverage.get('pending') and not coverage.get('result_limit_reached'):
        parts.append('本次仍有候选未处理，查询进度未能保存，请重新执行查询。')
    elif not page['has_more'] and page['returned']:
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
    retrieval = evidence.get('retrieval')
    if retrieval and '降级' in retrieval.get('mode', ''):
        parts.append('人才向量检索暂不可用，本次按文本相关性优先核验，仍保留其余候选。')
    return '\n\n'.join(parts)


def render_search_answer(evidence, rows):
    """Do not present relevance ranking as an exhaustive or model-verified result."""
    unresolved=evidence.get('unresolved_conditions',[])
    total=evidence['matched']; page=evidence['pagination']; plan=evidence['plan']
    parts=[f"本次检索返回 {total} 条{'待核验候选' if unresolved else '相关人才记录'}。" if total else
           '本次未召回符合当前筛选范围的相关记录，不代表资料中不存在相关人才。']
    if unresolved:
        parts.append('以下条件尚无法可靠执行，结果不能视为已满足这些要求：'+'；'.join(cell(c) for c in unresolved))
    if plan['sort_by'] and total:
        parts.append(f"其中 {evidence['rankable']} 条有 {cell(plan['sort_by'])}，按{'从高到低' if plan['descending'] else '从低到高'}排列。")
        if evidence['missing']:
            parts.append(f"另有 {evidence['missing']} 条缺少该指标，仍保留在后，沿用相关性顺序。")
        parts.append('排序仅覆盖当前召回结果，不代表全库精确排名。')
    unknown=evidence.get('coverage',{}).get('unknown',0)
    if unknown:
        parts.append(f'{unknown} 条记录缺少必要的筛选字段，未计入当前结果。')
    if page['returned']:
        parts.append(f"本次展示第 {page['offset']+1}—{page['offset']+page['returned']} 条。")
        columns=['姓名','当前机构','当前职务','领域','检索依据']
        if plan['sort_by']:columns.append(plan['sort_by'])
        lines=['| '+' | '.join(columns+['来源'])+' |','| '+' | '.join(['---']*(len(columns)+1))+' |']
        for row in rows:
            fields=row.fields
            name=next((v for k,v in fields.items() if k.casefold() in {'姓名','name','人员姓名','员工姓名','full name'}),'')
            lines.append('| '+' | '.join([cell(name if c=='姓名' else fields.get(c)) for c in columns]+[f'(Record {row.index})'])+' |')
        parts.append('\n'.join(lines))
    elif total:
        parts.append('当前结果已展示完，没有下一页。')
    retrieval=evidence.get('retrieval',{})
    if retrieval.get('vector_status') in {'warming','busy','empty','unavailable','disabled'} and plan.get('topic_condition'):
        parts.append('语义召回暂未就绪，本次使用文本相关性检索。')
    if evidence.get('unreadable_files'):
        parts.append('部分资料未能读取，本次结果未覆盖这些资料。')
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
    coverage=evidence.get('coverage', {})
    if coverage and (not coverage['complete'] or coverage['unknown'] or coverage.get('adjacent')):
        answer='以下为目前已确认的统计，不能视为全库精确总数。\n\n'+answer
        answer+=f"\n\n已核验 {coverage['evaluated']} / {coverage['eligible']} 条，待处理 {coverage['pending']} 条，资料不足或核验失败 {coverage['unknown']} 条。"
        if coverage.get('adjacent'):
            answer+=f"其中 {coverage['adjacent']} 条只有相近主题依据，具体主题关联仍待确认。"
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
        page=evidence.get('pagination')
        state=TalentQueryState(knowledge_base_id=payload.knowledge_base_id,query=query,
            snapshot_id=evidence.get('snapshot_id'),plan=evidence['plan'],offset=0,
            page_size=payload.talent_page_size,returned=0,has_more=page['has_more']) if page else None
        return AskResponse(answer=answer, provider_id=provider.id, model=payload.model or provider.default_model,
                           sources=[], row_sources=[], retrieval_query=query,query_state=state,
                           talent_coverage=evidence.get('coverage', {}))
    page = evidence['pagination']
    return AskResponse(answer=render_talent_answer(evidence, rows), provider_id=provider.id,
        model=payload.model or provider.default_model, sources=[], row_sources=rows, retrieval_query=query,
        talent_coverage=evidence.get('coverage', {}),
        query_state=TalentQueryState(knowledge_base_id=payload.knowledge_base_id, query=query,
            snapshot_id=evidence.get('snapshot_id'),
            plan=evidence['plan'], offset=page['offset'], page_size=page['page_size'],
            returned=page['returned'], has_more=page['has_more']))
