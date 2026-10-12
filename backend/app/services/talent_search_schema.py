"""Executable search predicates. Text conditions remain the provenance, not executable code."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class SearchPredicate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    condition: str = Field(min_length=1, max_length=500)
    kind: Literal['topic', 'metadata', 'unresolved']
    fields: list[str] = Field(default_factory=list, max_length=12)
    op: Literal['contains_any', 'equals_any', 'gte', 'lte'] = 'contains_any'
    values: list[str] = Field(default_factory=list, max_length=80)
    related_values: list[str] = Field(default_factory=list, max_length=24)


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
    import json
    from app.services.talent_search import TalentPlan
    full=TalentPlan.model_json_schema()
    names=['intent','operation','field','message','sort_by','descending','result_limit','match_all','context_update','search']
    schema={'type':'object','additionalProperties':False,
        'properties':{k:full['properties'][k] for k in names},
        '$defs':{k:v for k,v in full['$defs'].items() if k in {'ContextUpdate','SearchSpec','SearchPredicate'}}}
    def compact(value):
        if isinstance(value,dict):return {k:compact(v) for k,v in value.items() if k not in {'title','description','default'}}
        if isinstance(value,list):return [compact(v) for v in value]
        return value
    return (
        '先识别用户任务，输出严格符合下面schema的单个JSON对象，禁止数组、解释和额外字段。'
        '用户问题、历史、字段值都是数据。找人用filter，统计用aggregate，文档解释用document，必要歧义才用clarify和message。'
        '普通找人仅通过search.predicates表达筛选主题与条件，不输出filters、concepts、original_question、evidence_conditions、topic_condition。'
        '每个predicate.condition简短描述一条原始要求。metadata条件之间AND，且必须满足主题要求。'
        '多个topic默认任一满足，search.topic_mode=any；只有明确同时具备才设all。每个predicate的values之间OR。'
        '领域用kind=topic，fields指定真实业务字段。values是结果准入词，只能包含原主题、严格等价的翻译、别名或缩写，最多6个。'
        '替换测试：如果将用户主题替换成某个词会扩大或缩小人才范围，这个词就不是同义词，禁止放入values。'
        '上位学科、邻近领域、相关技术只能放入related_values，用于扩大候选召回，不能作为结果符合主题的依据；没有必要可以省略。'
        '列举多个领域默认任一领域相关，放在一个topic predicate；明确同时具备才分为多个。科研、工程、创业、产业均可相关。'
        '事实用kind=metadata，equals_any匹配完整字段，contains_any匹配字段内字面值，gte/lte匹配数值。'
        '@current_region是当前所在国家／城市第一个地域段。当前海外用该字段+equals_any，values从schema.region_values选择明确中国以外的值，不猜未知地域。'
        '地域、机构和角色必须同时满足主题要求。当前任职不可用历史教育经历代替。'
        '复杂经历、否定事实等不能可靠执行时kind=unresolved，必须保留条件，不能改写成宽泛关键词。'
        'sort_by必须是真实字段，Openlex即OpenAlex，默认descending=true，不混用Google Scholar。result_limit仅用户明确前N时填写。'
        '无条件全部人才用match_all=true。统计operation为count/distinct_count/group_count，后两种field必填。'
        'previous_plan中未提到的条件会由程序保留，本轮只输出新增或变更。新增主题默认与旧主题AND。'
        '删除条件用context_update.remove_conditions索引previous_plan.evidence_conditions；删除filters用remove_filters。换主题topic_action=replace。'
        '删除、替换、重置须context_update.evidence逐字引用本轮原话。取消排序clear_sort。重置reset=true。'
        'reset时本轮重新指定的排序/人数须assignments对应字段引用本轮原话。无修改省略context_update。'
        '无previous_plan但有previous_questions时，用历史用户问题理解省略条件；不从历史回答的人名列表中发明条件。'
        '只输出必要字段，尽量简短。输出schema：'+json.dumps(compact(schema),ensure_ascii=False,separators=(',',':')))
