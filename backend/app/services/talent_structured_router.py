"""Small, fail-closed query grammar over the authorized schema and entity values.

This is a fast lane, not a replacement for semantic planning. Every character
must belong to a supported operation; unknown entities, extra constraints and
ambiguous fields fall through to the planner without dropping any text.
"""
import re

from app.services.talent_search import TalentPlan, normalized
from app.services.talent_search_schema import SearchPredicate, SearchSpec, bind_relations

# Explicit geographic vocabulary, not an inference from employer or education.
# Unrecognized source regions prevent local compilation of the overseas facet.
DOMESTIC = {'中国', '中国大陆', '中国香港', '中国澳门', '中国台湾', '香港', '澳门', '台湾'}
OVERSEAS = set('美国 加拿大 北美 英国 爱尔兰 法国 德国 意大利 西班牙 葡萄牙 荷兰 比利时 瑞士 奥地利 瑞典 挪威 丹麦 芬兰 冰岛 波兰 捷克 希腊 澳大利亚 新西兰 新加坡 日本 韩国 印度 以色列 巴西 墨西哥 南非 阿联酋 沙特阿拉伯 马来西亚 泰国 印度尼西亚 越南'.split())
UNKNOWN = {'', '未知', '不详', '未提供', '—', '-', 'n/a', 'unknown'}


def sort_action(question, fields):
    query=normalized(question).strip('。？！?!')
    matches=[]
    for field in fields:
        # Sort only explicit numeric metrics. A partial or ambiguous metric name
        # is not silently mapped to another provider's metric.
        if not any(x in field.casefold() for x in ('h-index','引用数','作品数')):
            continue
        match=re.fullmatch(r'(?:请|帮我)?(?:按照|按)?'+re.escape(normalized(field))+
            r'(?P<direction>从高到低|从低到高|降序|升序)?(?:排序|排列|排名)?',query)
        if match:
            matches.append({'field':field,'descending':match['direction'] not in {'从低到高','升序'}})
    return matches[0] if len(matches)==1 else None


def _entity(query, sheets, field):
    """Only accept an unambiguous value actually present in this authorized corpus."""
    if not query or len(query)>150:
        return None
    from app.services.search_vocabulary import aliases as entity_aliases,contains
    equivalents=entity_aliases(query,institution=True)
    if len(equivalents)>1 and any(contains(str(row['fields'].get(field,'')),alias)
            for sheet in sheets for row in sheet.rows for alias in equivalents):
        return equivalents[0]
    aliases={}
    for sheet in sheets:
        for row in sheet.rows:
            value=str(row['fields'].get(field,''))
            for piece in re.split(r'[;；、\n（）()]',value):
                piece=piece.strip()
                if piece:aliases.setdefault(normalized(piece),set()).add(piece)
    matches=aliases.get(normalized(query),set())
    if matches:return sorted(matches)[0]
    # Institution cells commonly include a school, department or joint
    # appointment. Accept the requested organization name itself only when it
    # has an entity-shaped suffix and appears in an authorized current value.
    if len(normalized(query))>=4 and re.search(r'(大学|学院|研究院|研究所|实验室|公司|集团|中心|医院|基金会|Labs?|Lab|University|Institute|OpenAI)$',query,re.I):
        if any(normalized(query) in key for key in aliases):return query
    return None


def _topic(value, fields):
    value=value.strip()
    if not value or len(value)>80 or re.search(r'[，,、；;和与或及/]|不含|排除|除了|至少|至多|以上|以下|并且|而且|同时|以及',value):
        return None
    research=[f for f in ('领域','未来产业方向','细分关键词','研究方向','技术角色定位','详细个人简介','代表成果','创业／项目经历') if f in fields]
    if not research:return None
    return SearchPredicate(condition=f'{value}领域相关',kind='topic',fields=research,values=[value])


def topic_expression(query, prefix, suffix, *, legacy=False):
    activity = '' if legacy else r'(?:从事\s*)?'
    research = '' if legacy else r'(?:的?研究)?'
    match = re.fullmatch(prefix + activity + r'(.+?)(?:领域|方向)' + research + r'(?:相关)?' + suffix, query, re.I)
    return match[1].strip() if match else None


def repair_legacy_topic(previous, previous_question, sheets, current_question=None):
    """Repair only the old parser's provable activity-prefix capture, not user intent."""
    if not previous_question or not isinstance(previous, dict):
        return previous
    query = previous_question.strip().rstrip('。？！?!').strip()
    prefix = r'(?:请)?(?:帮我)?(?:查找|查询|筛选|找出|列出|搜索)?\s*'
    suffix = r'(?:的)?(?:人才|人员)(?:有哪些)?'
    old = topic_expression(query, prefix, suffix, legacy=True)
    clean = topic_expression(query, prefix, suffix)
    if not old or not clean or old == clean:
        return previous
    if current_question:
        current = topic_expression(current_question.strip().rstrip('。？！?!').strip(), prefix, suffix)
        if current and current.casefold() == clean.casefold():
            clean = current
    fields = {f for sheet in sheets for f in sheet.headers}
    replacement = _topic(clean, fields)
    original = _topic(old, fields)
    if replacement is None or original is None:
        return previous
    plan = TalentPlan.model_validate(previous)
    if not plan.search:
        return previous
    wrong = f'{old}领域相关'
    matches = [p for p in plan.search.predicates if p.kind == 'topic' and p.condition == wrong
               and p.values == [old] and p.fields == original.fields and p.op == original.op
               and p.relation is None and not p.related_values]
    if len(matches) != 1:
        return previous
    predicates = [replacement if p is matches[0] else p for p in plan.search.predicates]
    return plan.model_copy(update={
        'search': plan.search.model_copy(update={'predicates': predicates}),
        'evidence_conditions': list(dict.fromkeys(replacement.condition if c == wrong else c for c in plan.evidence_conditions)),
        'topic_condition': replacement.condition if plan.topic_condition == wrong else plan.topic_condition,
    }).model_dump()


def compile_structured(question, sheets):
    from app.services.talent_semantics import local_geo_intent, local_metric_intent,local_name_intent, compile_intent
    geo = local_geo_intent(question)
    if geo is not None:
        return compile_intent(geo, question, sheets)
    fields={f for s in sheets for f in s.headers}
    metric=local_metric_intent(question,fields)
    if metric is not None:return compile_intent(metric,question,sheets)
    named=local_name_intent(question,sheets)
    if named is not None:return compile_intent(named,question,sheets)
    sort=sort_action(question,fields)
    if sort:return compile_intent({'answer_mode':'list','sort_by':sort['field'],'descending':sort['descending']},question,sheets)
    query=re.sub(r'\s+',' ',question).strip().rstrip('。？！?!').strip()
    prefix=r'(?:请)?(?:帮我)?(?:查找|查询|筛选|找出|列出|搜索)?\s*'
    suffix=r'(?:的)?(?:人才|人员)(?:有哪些)?'
    predicate=None
    if re.fullmatch(prefix+r'(?:当前)?海外'+suffix,query):
        from app.services.talent_fast_search import region_value
        regions={region_value(row['fields']) for s in sheets for row in s.rows}
        if '所在国家／城市' not in fields or regions-DOMESTIC-OVERSEAS-UNKNOWN:
            return None
        allowed=sorted(regions & OVERSEAS)
        if not allowed:return None
        predicate=SearchPredicate(condition='当前所在地在海外',kind='metadata',fields=['@current_region'],op='equals_any',values=allowed)
    else:
        # Temporal relations are operations; organization names come from data.
        employment=re.fullmatch(prefix+r'在\s*(.+?)\s*工作过的(?:有哪些|人才|人员)',query,re.I)
        institution=re.fullmatch(prefix+r'(.+?)'+suffix,query,re.I)
        explicit=re.fullmatch(prefix+r'(?:当前机构(?:列)?(?:为|包含|是|[:：=])|当前任职(?:于|在)?)\s*(.+?)(?:的人才)?',query,re.I)
        if employment:
            entity=_entity(employment[1],sheets,'当前机构')
            if entity:
                predicate=SearchPredicate(condition=f'在{entity}有任职经历（含现任）',kind='metadata',
                    fields=['当前机构','工作经历'],values=[entity],relation='employment_experience',relation_evidence=question)
        if predicate is None and (institution or explicit):
            entity=_entity((explicit or institution)[1],sheets,'当前机构')
            if entity:
                predicate=SearchPredicate(condition=f'当前机构属于{entity}',kind='metadata',fields=['当前机构'],
                    values=[entity],relation='current_affiliation')
        if predicate is None:
            topic = topic_expression(query, prefix, suffix)
            if topic:
                # Only a whole controlled vocabulary value is an atomic topic.
                # Institution + activity + topic and unknown free text require
                # semantic planning; an arbitrary substring is never executable.
                from app.services.search_vocabulary import known_topic
                controlled={normalized(part) for sheet in sheets for row in sheet.rows
                    for field in ('领域','未来产业方向','细分关键词','研究方向')
                    for part in re.split(r'[、,，;；|\n]',str(row['fields'].get(field,''))) if part.strip()}
                if known_topic(topic) or normalized(topic) in controlled:predicate=_topic(topic,fields)
    if predicate is None:
        # The legacy domain+metric compiler checks the complete remainder and
        # only binds exact authorized domain values; it is not a topic wildcard.
        from app.services.talent_search import rule_plan
        return rule_plan(question,sheets)
    return bind_relations(TalentPlan(evidence_conditions=[predicate.condition],
        topic_condition=predicate.condition if predicate.kind=='topic' else '',
        search=SearchSpec(predicates=[predicate])),question)
