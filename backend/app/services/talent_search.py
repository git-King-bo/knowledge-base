"""Validated, read-only queries over complete personnel rows in uploaded workbooks."""
import json
import math
import re
from dataclasses import dataclass
from typing import Literal

from openpyxl import load_workbook
from pydantic import BaseModel, Field

NAME_FIELDS = {"姓名", "人员姓名", "员工姓名", "name", "full name"}
DOMAIN_FIELDS = {"领域", "未来产业方向", "细分关键词", "研究方向"}


class TalentFilter(BaseModel):
    field: str
    op: Literal["contains", "eq", "gte", "lte", "not_contains"] = "contains"
    value: str


class TalentPlan(BaseModel):
    filters: list[TalentFilter] = Field(default_factory=list, max_length=8)
    sort_by: str | None = None
    descending: bool = True
    limit: int = Field(default=20, ge=1, le=100)


@dataclass
class TalentSheet:
    source_id: str
    filename: str
    sheet: str
    headers: list[str]
    rows: list[dict]


def read_talent_sheets(sources) -> tuple[list[TalentSheet], list[str]]:
    sheets = []
    failures = []
    for source in sources:
        try:
            workbook = load_workbook(source.storage_path, read_only=True, data_only=True)
            try:
                for sheet in workbook.worksheets:
                    iterator = sheet.iter_rows(values_only=True)
                    header = None
                    name_field = None
                    records = []
                    for number, row in enumerate(iterator, 1):
                        values = [str(value).strip() if value is not None else "" for value in row]
                        if not any(values):
                            continue
                        if header is None:
                            header = values
                            name_field = next((field for field in header if field.casefold() in NAME_FIELDS), None)
                            if not name_field:
                                break
                            continue
                        fields = {field: values[index] if index < len(values) else ""
                                  for index, field in enumerate(header) if field}
                        if fields.get(name_field):
                            records.append({"row": number, "fields": fields})
                    if name_field:
                        sheets.append(TalentSheet(source.id, source.filename, sheet.title, header, records))
            finally:
                workbook.close()
        except Exception:
            failures.append(source.filename)
    return sheets, failures


def number_value(value: str) -> float | None:
    text = value.strip().replace(",", "").replace("，", "")
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text):
        return None
    value = float(text)
    return value if math.isfinite(value) else None


def normalized(value: str) -> str:
    return re.sub(r"[\s_‐‑–—-]+", "", value.casefold()).replace("openlex", "openalex")


def rule_plan(question: str, sheets: list[TalentSheet]) -> TalentPlan | None:
    """Common domain + metric queries need no model call; broader queries use a planner."""
    headers = {field for sheet in sheets for field in sheet.headers}
    query = normalized(question)
    filters = []
    domain_values = {row['fields'].get('领域', '') for sheet in sheets for row in sheet.rows}
    aliases = {"embodiedai": "具身智能", "embodiedintelligence": "具身智能",
               "人工智能科学": "AI4S", "aiforscience": "AI4S"}
    for alias, domain in aliases.items():
        if alias in query:
            query = query.replace(alias, normalized(domain))
    domains = sorted(value for value in domain_values if value and normalized(value) in query)
    if len(domains) > 1 or re.search(r"不含|排除|除了|大于|小于|至少|至多|超过|低于|高于|机构|大学|城市|国家", question):
        return None
    if domains:
        filters.append(TalentFilter(field="领域", op="contains", value=domains[0]))
    sort_fields = [field for field in headers if any(term in field.casefold() for term in ('h-index', '引用数', '作品数'))
                   and normalized(field) in query]
    if len(sort_fields) > 1:
        return None
    sort_by = sort_fields[0] if sort_fields else None
    if not filters and not sort_by:
        return None
    # Do not silently turn an ambiguous ranking metric into another provider's metric.
    if re.search(r"排名|排序|排行|最高|最低|h.?index|引用", question, re.I) and not sort_by:
        return None
    limit_match = re.search(r"(?:前|top\s*)(\d+)", question, re.I)
    remainder = query
    for value in domains + ([sort_by] if sort_by else []):
        remainder = remainder.replace(normalized(value), '')
    remainder = re.sub(r"(?:前|top)\d+", '', remainder)
    for word in ['帮我', '请', '查询', '查找', '搜索', '筛选', '找出', '领域', '并且', '按照', '按',
                 '排名', '排序', '排行', '从高到低', '从低到高', '从大到小', '从小到大', '降序', '升序',
                 '最高', '最低', '人才', '人员', '信息', '列表', '列出', '的', '，', '。', ',', '.', '？', '?']:
        remainder = remainder.replace(word, '')
    if remainder:
        return None
    return TalentPlan(filters=filters, sort_by=sort_by,
                      descending=not bool(re.search(r"升序|从低到高|从小到大|最低", question)),
                      limit=min(100, max(1, int(limit_match[1]))) if limit_match else 20)


def validate_plan(plan: TalentPlan, sheets: list[TalentSheet]) -> TalentPlan:
    headers = {field for sheet in sheets for field in sheet.headers if field}
    if any(item.field not in headers or not item.value.strip() for item in plan.filters):
        raise ValueError("筛选字段不存在或条件为空")
    if any(item.op in {'gte', 'lte'} and number_value(item.value) is None for item in plan.filters):
        raise ValueError("数值筛选条件必须是有效数字")
    if plan.sort_by is not None and plan.sort_by not in headers:
        raise ValueError("排序字段不存在")
    if not plan.filters and not plan.sort_by:
        raise ValueError("缺少明确的筛选条件或排序字段")
    return plan


def execute_plan(plan: TalentPlan, sheets: list[TalentSheet]) -> list[dict]:
    validate_plan(plan, sheets)
    results = []
    for sheet in sheets:
        needed = {item.field for item in plan.filters} | ({plan.sort_by} if plan.sort_by else set())
        if not needed.issubset(set(sheet.headers)):
            results.append({"file": sheet.filename, "sheet": sheet.sheet, "error": "缺少查询所需字段"})
            continue
        def matches(row):
            for item in plan.filters:
                actual = row['fields'].get(item.field, '')
                if item.op in {'gte', 'lte'}:
                    value, target = number_value(actual), number_value(item.value)
                    if value is None or target is None or (value < target if item.op == 'gte' else value > target):
                        return False
                elif item.op == 'eq' and normalized(actual) != normalized(item.value):
                    return False
                elif item.op == 'contains' and normalized(item.value) not in normalized(actual):
                    return False
                elif item.op == 'not_contains' and normalized(item.value) in normalized(actual):
                    return False
            return True
        matched = [row for row in sheet.rows if matches(row)]
        missing = 0
        ordered = matched
        if plan.sort_by:
            ordered = [row for row in matched if number_value(row['fields'].get(plan.sort_by, '')) is not None]
            missing = len(matched) - len(ordered)
            ordered.sort(key=lambda row: number_value(row['fields'][plan.sort_by]), reverse=plan.descending)
        selected_fields = set(NAME_FIELDS) | DOMAIN_FIELDS | {
            '当前机构', '当前职务', '所在国家／城市', 'OpenAlex主页', 'OpenAlex h-index',
            'Google Scholar h-index', 'OpenAlex指标更新时间',
            '来源链接', '证据链接', 'Google Scholar主页',
        } | needed
        records = [{"excel_row": row['row'], "fields": {key: value for key, value in row['fields'].items()
                    if key in selected_fields or key.casefold() in NAME_FIELDS}} for row in ordered[:plan.limit]]
        results.append({"source_id": sheet.source_id, "file": sheet.filename, "sheet": sheet.sheet,
                        "scanned_records": len(sheet.rows), "matched_records": len(matched),
                        "missing_sort_values": missing, "rankable_records": len(ordered),
                        "returned_records": len(records), "truncated": len(ordered) > len(records),
                        "plan": plan.model_dump(), "records": records})
    return results


def talent_context(question: str, sources, planner=None, *, max_results: int = 5) -> str | None:
    sheets, failures = read_talent_sheets(sources)
    if not sheets:
        return None
    plan = rule_plan(question, sheets)
    # General document Q&A and simple whole-file counts keep the existing route.
    candidate = bool(re.search(r"领域|研究方向|人才|排名|排序|排行|h.?index|筛选|查找|查询|找出|推荐|机构|城市", question, re.I))
    if plan is None and not candidate:
        return None
    if plan is None and planner:
        schema = {"fields": sorted({field for sheet in sheets for field in sheet.headers if field}),
                  "domains": sorted({row['fields'].get('领域', '') for sheet in sheets for row in sheet.rows} - {''})}
        try:
            raw = planner(schema)
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
            plan = validate_plan(TalentPlan.model_validate_json(raw), sheets)
        except Exception:
            plan = None
    if plan is None:
        return "人才表已找到，但无法可靠确定本次筛选或排序条件。请明确领域和指标来源，例如：具身智能领域，按 OpenAlex h-index 降序排列前20名。"
    plan = plan.model_copy(update={"limit": min(plan.limit, max_results)})
    results = execute_plan(plan, sheets)
    candidates = [(index, record) for index, result in enumerate(results) for record in result.get('records', [])]
    if plan.sort_by:
        candidates.sort(key=lambda item: number_value(item[1]['fields'][plan.sort_by]), reverse=plan.descending)
    selected = {(index, record['excel_row']) for index, record in candidates[:plan.limit]}
    for index, result in enumerate(results):
        if 'error' in result:
            continue
        result['records'] = [record for record in result['records'] if (index, record['excel_row']) in selected]
        result['returned_records'] = len(result['records'])
        result['truncated'] = result['rankable_records'] > len(result['records'])
    return json.dumps({"results": results, "unreadable_files": failures, "max_returned_records": plan.limit,
                       "scope_note": f"全表筛选和统计，所有文件合计最多展示{plan.limit}条人员记录；命中总数不是展示数量。各文件独立统计，不按姓名去重。缺失或非数值指标不参与排名。"}, ensure_ascii=False)
