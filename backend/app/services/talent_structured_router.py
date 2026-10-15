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
    if not value or len(value)>80 or re.search(r'[，,、；;和与或及/]|不含|排除|除了|至少|至多|以上|以下',value):
        return None
    research=[f for f in ('领域','未来产业方向','细分关键词','研究方向','技术角色定位','详细个人简介','代表成果','创业／项目经历') if f in fields]
    if not research:return None
    return SearchPredicate(condition=f'{value}领域相关',kind='topic',fields=research,values=[value])


def compile_structured(question, sheets):
    fields={f for s in sheets for f in s.headers}
    sort=sort_action(question,fields)
    if sort:return TalentPlan(sort_by=sort['field'],descending=sort['descending'])
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
        institution_topic=re.fullmatch(prefix+r'(.+?)(.+?)(?:领域|方向)(?:相关)?'+suffix,query,re.I)
        if employment:
            entity=_entity(employment[1],sheets,'当前机构')
            if entity:
                predicate=SearchPredicate(condition=f'在{entity}有任职经历（含现任）',kind='metadata',
                    fields=['当前机构','工作经历'],values=[entity],relation='employment_experience',relation_evidence=question)
        elif institution_topic:
            # Pick the longest institution prefix that is supported by current
            # affiliation data; the residual phrase is one literal topic.
            joined=institution_topic[1]+institution_topic[2]
            candidates=[]
            for end in range(1,len(joined)):
                entity=_entity(joined[:end],sheets,'当前机构')
                topic=_topic(joined[end:],fields)
                if entity and topic:candidates.append((end,entity,topic))
            if candidates:
                _,entity,topic=max(candidates,key=lambda item:item[0])
                current=SearchPredicate(condition=f'当前机构属于{entity}',kind='metadata',fields=['当前机构'],values=[entity],relation='current_affiliation')
                return bind_relations(TalentPlan(evidence_conditions=[current.condition,topic.condition],topic_condition=topic.condition,
                    search=SearchSpec(predicates=[current,topic],topic_mode='all')),question)
        if predicate is None and (institution or explicit):
            entity=_entity((explicit or institution)[1],sheets,'当前机构')
            if entity:
                predicate=SearchPredicate(condition=f'当前机构属于{entity}',kind='metadata',fields=['当前机构'],
                    values=[entity],relation='current_affiliation')
        if predicate is None:
            topic_match=re.fullmatch(prefix+r'(.+?)(?:领域|方向)(?:相关)?'+suffix,query,re.I)
            if topic_match:predicate=_topic(topic_match[1],fields)
    if predicate is None:
        from app.services.talent_search import rule_plan
        return rule_plan(question,sheets)
    return bind_relations(TalentPlan(evidence_conditions=[predicate.condition],
        topic_condition=predicate.condition if predicate.kind=='topic' else '',
        search=SearchSpec(predicates=[predicate])),question)
