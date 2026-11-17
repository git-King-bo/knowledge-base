"""Typed intent -> grounded predicates. Model prose never chooses executable columns."""
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from app.services.talent_search_schema import SearchPredicate, SearchSpec

SLOTS = ('topic','current_region','current_location','current_institution','institution_country',
         'institution_type','education','employment_history','employment_experience','any_affiliation','position','metric','unresolved')
RESEARCH = ('领域','未来产业方向','细分关键词','研究方向','技术角色定位','详细个人简介','代表成果','创业／项目经历')
COUNTRY_FIELDS = ('机构国别','机构所在国家','院校所在国家','机构国家')
TYPE_FIELDS = ('机构类型','院校类型')
COUNTRY_ALIASES = {
    '美国': ('美国','美國','US','USA','United States'), '英国': ('英国','英國','UK','United Kingdom'),
    '中国': ('中国','中國','China'), '加拿大': ('加拿大','Canada'), '德国': ('德国','德國','Germany'),
    '法国': ('法国','法國','France'), '日本': ('日本','Japan'), '韩国': ('韩国','South Korea'),
    '新加坡': ('新加坡','Singapore'), '澳大利亚': ('澳大利亚','Australia'), '新西兰': ('新西兰','New Zealand'),
    '瑞士': ('瑞士','Switzerland'), '意大利': ('意大利','Italy'), '荷兰': ('荷兰','Netherlands'),
    '瑞典': ('瑞典','Sweden'), '以色列': ('以色列','Israel'), '印度': ('印度','India'),
}
TYPE_WORDS = {'university': ('院校','高校','大学','学院','学校','university','college'),
              'company': ('公司','企业','company','corporation'),
              'hospital': ('医院','hospital'), 'research_institute': ('研究所','研究院','research institute')}


def country(value):
    value=value.strip().casefold()
    for canonical,aliases in COUNTRY_ALIASES.items():
        if value in {a.casefold() for a in aliases}: return canonical
    from app.services.talent_structured_router import DOMESTIC, OVERSEAS
    return next((v for v in DOMESTIC|OVERSEAS if value==v.casefold()), None)


def mentioned(value, text):
    if re.fullmatch(r'[A-Za-z ]+',value):
        return bool(re.search(r'(?<![A-Za-z])'+re.escape(value)+r'(?![A-Za-z])',text,re.I))
    return value.casefold() in text.casefold()


def country_evidence(value,text):
    return any(mentioned(a,text) for a in COUNTRY_ALIASES.get(value,(value,)))


def institution_type(fields):
    for key in TYPE_FIELDS:
        if fields.get(key):
            raw=str(fields[key]).casefold()
            return next((kind for kind,words in TYPE_WORDS.items() if raw==kind or any(raw==w.casefold() for w in words)),None)
    raw=str(fields.get('当前机构',''))
    # Only explicit name evidence; acronyms and unclassified names remain unknown.
    found={kind for kind,words in TYPE_WORDS.items() if any(mentioned(w,raw) for w in words)}
    return next(iter(found)) if len(found)==1 else None


def infer_slot(predicate):
    if predicate.slot:
        if predicate.slot not in SLOTS: raise ValueError('Unknown semantic slot')
        return predicate.slot
    if predicate.kind=='topic': return 'topic'
    fields=set(predicate.fields)
    if fields & {'@current_region','所在国家／城市'}: return 'current_region' if all(country(v) for v in predicate.values) else 'current_location'
    if fields & set(COUNTRY_FIELDS): return 'institution_country'
    if fields & set(TYPE_FIELDS) or '@institution_type' in fields: return 'institution_type'
    if predicate.relation: return {'current_affiliation':'current_institution'}.get(predicate.relation,predicate.relation)
    if fields=={'当前机构'}: return 'current_institution'
    if fields=={'教育经历'}: return 'education'
    if fields=={'工作经历'}: return 'employment_history'
    if fields=={'当前职务'}: return 'position'
    if predicate.op in {'gte','lte'}: return 'metric'
    return None


def schema_catalog(fields):
    fields=set(fields)
    return {
        'current_region': ['@current_region'] if '所在国家／城市' in fields else [],
        'current_location': ['所在国家／城市'] if '所在国家／城市' in fields else [],
        'institution_country': [f for f in COUNTRY_FIELDS if f in fields],
        'institution_type': ['@institution_type'] if '当前机构' in fields or fields & set(TYPE_FIELDS) else [],
        'current_institution': ['当前机构'] if '当前机构' in fields else [],
        'education': ['教育经历'] if '教育经历' in fields else [],
        'employment_history': ['工作经历'] if '工作经历' in fields else [],
        'employment_experience': [f for f in ('当前机构','工作经历') if f in fields],
        'any_affiliation': [f for f in ('当前机构','工作经历','教育经历') if f in fields],
        'position': ['当前职务'] if '当前职务' in fields else [],
        'topic': [f for f in RESEARCH if f in fields],
        'metric': [f for f in fields if any(x in f.casefold() for x in ('h-index','引用数','作品数'))],
    }


def bind_semantics(plan, sheets):
    if not plan.search: return plan
    catalog=schema_catalog(f for s in sheets for f in s.headers)
    predicates=[];names={}
    for p in plan.search.predicates:
        slot=infer_slot(p)
        if slot=='current_institution' and p.values and all(country(v) for v in p.values):
            # Reject the historical country-as-institution-name error at execution boundary.
            slot='institution_country'
        changes={'slot':slot}
        if slot in ('current_region','institution_country'):
            canonical=[country(v) for v in p.values]
            if all(canonical): changes.update(values=canonical,op='equals_any')
        if slot in catalog:
            fields=catalog[slot]
            if slot=='metric': fields=[f for f in p.fields if f in fields]
            if not fields:
                reason='缺少可核验的机构国别字段；若想按人才当前所在地筛选，请明确说明' if slot=='institution_country' else f'缺少{slot}的可核验字段'
                changes.update(kind='unresolved',fields=[],condition=p.condition if reason in p.condition else f'{p.condition}（{reason}）',relation=None)
            elif p.kind!='unresolved':
                changes['fields']=fields
                if slot in ('current_institution','education','employment_history','employment_experience','any_affiliation'):
                    changes['relation']='current_affiliation' if slot=='current_institution' else slot
                if slot=='institution_type': changes.update(relation=None,op='equals_any')
                if slot in ('current_region','current_location','institution_country'): changes['relation']=None
        q=p.model_copy(update=changes)
        names[p.condition]=q.condition;predicates.append(q)
    return plan.model_copy(update={'search':plan.search.model_copy(update={'predicates':predicates}),
        'evidence_conditions':list(dict.fromkeys(names.get(c,c) for c in plan.evidence_conditions)),
        'topic_condition':names.get(plan.topic_condition,plan.topic_condition)})


class Facet(BaseModel):
    model_config=ConfigDict(extra='forbid')
    slot: Literal['topic','current_region','current_location','current_institution','institution_country','institution_type','education','employment_history','employment_experience','any_affiliation','position','metric','unresolved']
    values: list[str]=Field(min_length=1,max_length=12)
    evidence: str=Field(min_length=1,max_length=500)
    op: Literal['contains_any','equals_any','gte','lte']='contains_any'
    mode: Literal['add','set']='add'
    field: str | None=None


class Intent(BaseModel):
    model_config=ConfigDict(extra='forbid')
    facets: list[Facet]=Field(default_factory=list,max_length=5)
    sort_by: str | None=None
    descending: bool=True
    result_limit: int | None=Field(default=None,ge=1,le=100)
    remove: list[str]=Field(default_factory=list,max_length=5)
    reset: bool=False
    evidence: str=''
    operation: Literal['count','distinct_count','group_count'] | None=None
    field: str | None=None
    basis: Literal['current_region'] | None=None


def compile_intent(data,question,sheets,previous=None):
    from app.services.talent_search import TalentPlan,ContextUpdate,normalized
    intent=Intent.model_validate(data)
    prior=TalentPlan.model_validate(previous) if previous else None
    predicates=[];remove=set()
    if intent.basis:
        if not prior or not prior.search or not intent.evidence or intent.evidence not in question or not any(w in intent.evidence for w in ('所在地','现居','当前所在')):
            raise ValueError('Changing geographic basis requires explicit evidence and prior state')
        pending=[p for p in prior.search.predicates if p.slot=='institution_country' and p.kind=='unresolved']
        if len(pending)!=1: raise ValueError('Geographic basis is ambiguous')
        old=pending[0]
        predicates.append(SearchPredicate(condition='当前所在地：'+'、'.join(old.values),kind='metadata',slot='current_region',evidence=intent.evidence,values=old.values,fields=['@current_region'],op='equals_any'))
        remove.add(prior.evidence_conditions.index(old.condition))
        for p in prior.search.predicates:
            if infer_slot(p)=='current_region' and p.condition in prior.evidence_conditions:
                remove.add(prior.evidence_conditions.index(p.condition))
    labels={'topic':'研究领域','current_region':'当前所在地','current_location':'当前地点',
            'institution_country':'机构国别','institution_type':'机构类型','current_institution':'当前机构',
            'education':'教育经历','employment_history':'历史任职','employment_experience':'任职经历','any_affiliation':'机构关联','position':'职务','metric':'指标','unresolved':'待核验要求'}
    for facet in intent.facets:
        if facet.evidence not in question: raise ValueError('Facet evidence must quote current question')
        if facet.slot=='current_region' and any(v.casefold() in ('海外','国外','overseas','abroad') for v in facet.values):
            if len(facet.values)!=1 or not any(mentioned(w,facet.evidence) for w in ('海外','国外','overseas','abroad')):raise ValueError('Invalid regional group')
            from app.services.talent_structured_router import OVERSEAS
            facet=facet.model_copy(update={'values':sorted(OVERSEAS)})
            # The group itself is the source evidence for its canonical members.
            group=True
        else:group=False
        if facet.slot in ('current_region','institution_country'):
            if not group and any(not country(v) or not country_evidence(country(v),facet.evidence) for v in facet.values):
                raise ValueError('Country must be grounded in the current expression')
        if facet.slot=='current_institution' and any(country(v) for v in facet.values):
            raise ValueError('A country cannot be an institution entity')
        if facet.slot=='institution_type':
            if any(v not in TYPE_WORDS or not any(mentioned(w,facet.evidence) for w in TYPE_WORDS[v]) for v in facet.values):
                raise ValueError('Institution type requires grounded type evidence')
        if facet.slot=='metric':
            metrics=schema_catalog(f for sheet in sheets for f in sheet.headers)['metric']
            if facet.field not in metrics or facet.op not in ('gte','lte'):raise ValueError('Invalid metric binding')
        kind='topic' if facet.slot=='topic' else ('unresolved' if facet.slot=='unresolved' else 'metadata')
        fields=[facet.field] if facet.field else []
        p=SearchPredicate(condition=labels[facet.slot]+'：'+'、'.join(facet.values),kind=kind,
            slot=facet.slot,evidence=facet.evidence,relation_evidence=facet.evidence,fields=fields,op=facet.op,values=facet.values)
        predicates.append(p)
        if facet.mode=='set' and prior and prior.search:
            for old in prior.search.predicates:
                if infer_slot(old)==facet.slot and old.condition in prior.evidence_conditions:
                    remove.add(prior.evidence_conditions.index(old.condition))
    for slot in intent.remove:
        if slot not in SLOTS or not intent.evidence or intent.evidence not in question: raise ValueError('Removal must target a known slot with evidence')
        if prior and prior.search:
            for old in prior.search.predicates:
                if infer_slot(old)==slot and old.condition in prior.evidence_conditions:remove.add(prior.evidence_conditions.index(old.condition))
    if intent.reset and (not intent.evidence or intent.evidence not in question):raise ValueError('Reset requires evidence')
    plan=TalentPlan(intent='aggregate' if intent.operation else 'filter',operation=intent.operation,field=intent.field,
        sort_by=intent.sort_by,descending=intent.descending,result_limit=intent.result_limit,
        evidence_conditions=[p.condition for p in predicates],topic_condition=next((p.condition for p in predicates if p.kind=='topic'),''),
        search=SearchSpec(predicates=predicates,topic_mode='all'),
        context_update=ContextUpdate(reset=intent.reset,remove_conditions=sorted(remove),evidence=intent.evidence or question))
    return bind_semantics(plan,sheets)


def deterministic_region_change(current,previous,question):
    """Only independently grounded same-slot country replacement skips semantic review."""
    change=current.context_update
    if change.reset or change.remove_filters or change.clear_sort or change.clear_limit or change.clear_topic or change.topic_action=='replace':return False
    if not change.remove_conditions or not current.search or not previous.search:return False
    replacements={p.slot:p for p in current.search.predicates if p.slot in ('current_region','institution_country')
                  and p.evidence and p.evidence in question and p.values and all(country(v) and country_evidence(country(v),p.evidence) for v in p.values)}
    old={p.condition:p for p in previous.search.predicates}
    basis_region=next((p for p in current.search.predicates if p.slot=='current_region'
        and p.evidence and p.evidence in question and any(w in p.evidence for w in ('所在地','现居','当前所在'))
        and any(before.slot=='institution_country' and before.kind=='unresolved' and before.values==p.values
                for before in previous.search.predicates)),None)
    def supported(index):
        before=old.get(previous.evidence_conditions[index])
        if before is None:return False
        if infer_slot(before) in replacements:return True
        return bool(basis_region and (infer_slot(before)=='current_region' or
            before.slot=='institution_country' and before.kind=='unresolved' and basis_region.values==before.values))
    return all(supported(i) for i in change.remove_conditions)



def local_geo_intent(question,previous=None):
    """A complete, schema-independent command grammar over canonical geographic entities."""
    if previous and re.fullmatch(r'(?:请)?(?:按|以)(?:人才)?(?:当前)?(?:所在地|现居地)(?:为准|筛选|查询)?[。！!]*',question.strip()):
        return {'basis':'current_region','evidence':question.strip()}
    from app.services.talent_structured_router import DOMESTIC,OVERSEAS
    aliases={alias:canonical for canonical,words in COUNTRY_ALIASES.items() for alias in words}
    aliases.update({v:v for v in DOMESTIC|OVERSEAS})
    names='|'.join(re.escape(a) for a in sorted(aliases,key=len,reverse=True))
    pattern=r'(?:请|帮我|请帮我)?(?:查找|查询|搜索|列出|看看)?(?:其中|那|换成|改成|再看)?\s*('+names+r')\s*(?:的)?(院校|高校|大学|学院|学校)?(?:的)?(?:人才|人员)?(?:有吗|有么|有哪些|呢)?[。？！?!]*'
    match=re.fullmatch(pattern,question.strip(),re.I)
    if not match:return None
    value=next(aliases[a] for a in aliases if a.casefold()==match[1].casefold())
    slot='institution_country' if match[2] else 'current_region'
    facets=[{'slot':slot,'values':[value],'evidence':match[1],'mode':'set'}]
    if match[2]:facets.append({'slot':'institution_type','values':['university'],'evidence':match[2]})
    return {'facets':facets}


def intent_instructions():
    return (
        '将用户本轮人才搜索意图编译为单个JSON增量，不返回名单、解释、SQL或物理列名。'
        '格式：{"facets":[{"slot":"...","values":["..."],"evidence":"本轮原话","mode":"add或set"}],"sort_by":"真实指标字段（可省略）"}。'
        'facets.slot只能为：'+','.join(SLOTS)+'。'
        'current_region=人才当前所在地的国家/地域；institution_country=机构本身国别，两者不能互换。'
        '英国院校/美国高校等分别输出institution_country和institution_type=university；不可在current_institution中填国家或类型。'
        '院校类型只允许university/company/hospital/research_institute，证据引用当前表达；缺少字段由程序处理，不得自行换成其他列。'
        'topic填原始研究主题，不能把从事、研究等活动词当领域，不能把能力评价当主题。'
        'current_institution只填真实机构实体；education/ employment_history/ employment_experience区分教育、历史任职及含现任的任职经历。'
        'metric需field为schema中的真实数值指标，op为gte或lte，values一个数字。其他op为contains_any或equals_any。'
        '每个facet.evidence必须逐字引用当前问题，国家用规范名称且须来自本轮表述。'
        '只输出本轮变化；未提及的主题/机构/排序会继承。国家切换等同维度改值mode=set；增加条件mode=add。'
        '用户明确改按所在地/现居地时可输出basis:current_region及evidence，程序沿用之前待确认的国家并转换依据，不能擅自转换机构国别。'
        '取消用remove:[slot]并给顶层evidence，重新开始reset:true并给evidence；不得用删除无关条件处理字段不可用。'
        '显式排名可填sort_by、descending和result_limit；不明确要求前N则省略result_limit。'
        '统计可填operation=count/distinct_count/group_count，后两者field必填。'
        '复杂无法可靠表达的事实用unresolved，不能删除条件或用宽泛关键词替代。只输出必要字段。'
    )


def previous_intent(plan):
    if not plan:return None
    return {'facets':[{'slot':infer_slot(p),'values':p.values,'pending':p.kind=='unresolved'} for p in (plan.search.predicates if plan.search else [])],
            'sort_by':plan.sort_by,'descending':plan.descending,'result_limit':plan.result_limit}
