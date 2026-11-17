"""Executable search predicates. Text conditions remain the provenance, not executable code."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class SearchPredicate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    condition: str = Field(min_length=1, max_length=500)
    slot: str | None = Field(default=None, max_length=40)
    evidence: str = Field(default='', max_length=500)
    kind: Literal['topic', 'metadata', 'unresolved']
    fields: list[str] = Field(default_factory=list, max_length=12)
    op: Literal['contains_any', 'equals_any', 'gte', 'lte'] = 'contains_any'
    values: list[str] = Field(default_factory=list, max_length=80)
    related_values: list[str] = Field(default_factory=list, max_length=24)
    relation: Literal['current_affiliation', 'education', 'employment_history', 'employment_experience', 'any_affiliation'] | None = None
    relation_evidence: str = Field(default='', max_length=500)


RELATION_FIELDS = {
    'current_affiliation': ['当前机构'],
    'education': ['教育经历'],
    'employment_history': ['工作经历'],
    'employment_experience': ['当前机构', '工作经历'],
    'any_affiliation': ['当前机构', '教育经历', '工作经历'],
}


def predicate_fields(predicate):
    """Bind relation semantics to source columns; mixed columns cannot widen current affiliation."""
    if predicate.kind == 'metadata':
        if predicate.relation:
            return RELATION_FIELDS[predicate.relation]
        if '当前机构' in predicate.fields:
            return RELATION_FIELDS['current_affiliation']
    return predicate.fields


def bind_relations(plan, question):
    if not plan.search:
        return plan
    predicates=[]
    for predicate in plan.search.predicates:
        if predicate.relation:
            if predicate.kind != 'metadata':
                raise ValueError('Affiliation relations must be metadata predicates')
            if predicate.relation != 'current_affiliation' and (
                    not predicate.relation_evidence.strip() or predicate.relation_evidence not in question):
                raise ValueError('Historical affiliation requires evidence from the current question')
        relation=predicate.relation
        if predicate.kind == 'metadata' and not relation and '当前机构' in predicate.fields:
            relation='current_affiliation'
        if relation and predicate.op not in {'contains_any', 'equals_any'}:
            raise ValueError('Affiliation relations require text membership')
        predicates.append(predicate.model_copy(update={
            'relation': relation, 'fields': list(predicate_fields(predicate)),
            # Source affiliation cells may contain departments or multiple
            # appointments. Institution membership is not whole-cell equality.
            'op': 'contains_any' if relation else predicate.op}))
    return plan.model_copy(update={'search': plan.search.model_copy(update={'predicates': predicates})})


class SearchSpec(BaseModel):
    model_config = ConfigDict(extra='forbid')
    predicates: list[SearchPredicate] = Field(default_factory=list, max_length=5)
    topic_mode: Literal['any','all'] = 'any'


def search_instructions():
    return (
        '\n普通人才查询使用混合搜索，不会逐人调用大模型核验。必须输出search.predicates来编译全部条件。'
        '每个predicate.condition必须逐字等于一个evidence_conditions或topic_condition；不能发明或遗漏条件。'
        '主题用kind=topic，values提供本主题中英文同义词，fields提供实际业务字段；多个替代主题可放在同一predicate中，表示或。'
        '明确同时满足多个主题时使用多个topic predicate，表示并且。不要用过于宽泛的上位词替代具体主题。'
        '事实筛选用kind=metadata，fields指定真实字段，values提供允许值。equals_any匹配完整规范字段，contains_any匹配字段内字面值。'
        '特殊字段@current_region来自当前所在国家／城市列的第一个地域段，schema.region_values是实际可用值。'
        '当前海外人才使用@current_region + equals_any，values从region_values中选择明确位于中国以外的地域；不选未知、无法判定或中国境内地域。'
        '不能用历史教育经历证明当前所在地，不能用当前所在地证明历史经历。'
        '机构、职位可用真实当前字段和中英文别名筛选，不得只拿宽泛词替代实体。'
        'gte/lte只用于明确的数值条件，values恰好一个数字。'
        '复杂关系、否定经历或无法由现有字段可靠表达的事实，kind=unresolved，不猜测，不删除。'
        '继承条件的已有编译结果由程序保留；本轮新增的每个条件必须给出对应predicate。'
        '无需返回长message或解释，不返回人才名单。'
    )


def fast_query_instructions():
    from app.services.talent_semantics import intent_instructions
    return intent_instructions()
