"""Lossless extraction of the existing MVP talent spreadsheet (no model calls)."""
import json
from datetime import date, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from openpyxl import load_workbook

FIELDS = {'name': '姓名', 'organization': '当前机构', 'position': '当前职务', 'biography': '详细个人简介', 'education': '教育经历', 'work_experience': '工作经历', 'projects': '创业／项目经历', 'achievements': '代表成果', 'talent_identity': '人才身份', 'industry_direction': '未来产业方向', 'keywords': '细分关键词', 'public_views': '公开观点', 'contact_clues': '公开联系方式线索', 'source_links': '来源链接', 'change_summary': '本次变化摘要', 'pending_confirmation': '待人工确认事项', 'last_auto_update': '上次自动更新时间', 'auto_update_result': '自动更新结果', 'operation_records': '关联运营记录', 'location': '所在国家／城市', 'english_name': '英文名', 'technical_role': '技术角色定位', 'evidence_links': '证据链接', 'scholar_citations': 'Google Scholar总引用数', 'scholar_url': 'Google Scholar主页', 'scholar_h_index': 'Google Scholar h-index', 'academic_updated_at': '学术指标更新时间', 'open_source_assets': '开源资产摘要', 'openalex_url': 'OpenAlex主页', 'openalex_works': 'OpenAlex作品数', 'openalex_citations': 'OpenAlex总引用数', 'openalex_h_index': 'OpenAlex h-index', 'openalex_updated_at': 'OpenAlex指标更新时间', 'research_document': '深度调研文档', 'domain': '领域'}


def normalize(value):
    return value.isoformat() if isinstance(value, (date, datetime)) else value


def read_talents(path: Path, source_id: str) -> list[dict]:
    values = load_workbook(path, read_only=True, data_only=True)
    formulas = load_workbook(path, read_only=True, data_only=False)
    records = []
    try:
        for sheet in values:
            value_rows = sheet.iter_rows(values_only=True)
            formula_rows = formulas[sheet.title].iter_rows(values_only=True)
            headers = list(next(value_rows, ()))
            next(formula_rows, None)
            if not headers:
                continue
            if headers != list(FIELDS.values()):
                raise ValueError(f"Unexpected headers in {sheet.title}; no data imported")
            for row_number, (row, original) in enumerate(zip(value_rows, formula_rows, strict=True), 2):
                if all(v is None for v in original):
                    continue
                if not row[0] or not str(row[0]).strip():
                    raise ValueError(f"Missing name at {sheet.title}:{row_number}")
                raw = {h: normalize(v) for h, v in zip(headers, row, strict=True)}
                expressions = {h: v for h, v in zip(headers, original, strict=True)
                               if isinstance(v, str) and v.startswith("=")}
                records.append(dict(
                    id=str(uuid5(NAMESPACE_URL, f"talent:{source_id}:{sheet.title}:{row_number}")),
                    source_id=source_id, sheet_name=sheet.title, source_row=row_number,
                    raw_data_json=json.dumps(raw, ensure_ascii=False),
                    formulas_json=json.dumps(expressions, ensure_ascii=False),
                    **{field: None if raw[h] is None else str(raw[h]) for field, h in FIELDS.items()},
                ))
        return records
    finally:
        values.close()
        formulas.close()


def read_personnel(path: Path, source_id: str) -> list[dict]:
    """Accept named personnel sheets; retain unknown fields and formulas verbatim."""
    if path.suffix.lower() != '.xlsx':
        return []
    values = load_workbook(path, read_only=True, data_only=True)
    formulas = load_workbook(path, read_only=True, data_only=False)
    result = []
    try:
        for sheet in values:
            rows = sheet.iter_rows(values_only=True)
            originals = formulas[sheet.title].iter_rows(values_only=True)
            headers = None
            for number, (row, raw) in enumerate(zip(rows, originals, strict=True), 1):
                if not any(v is not None for v in raw):
                    continue
                if headers is None:
                    headers = [str(v).strip() if v is not None else f'未命名列{i+1}' for i,v in enumerate(row)]
                    if len(set(headers)) != len(headers):
                        raise ValueError('存在重复表头，请修正后重新导入')
                    name_field = next((h for h in headers if h.lower() in {'姓名','人员姓名','员工姓名','name','full name'}),None)
                    if not name_field:
                        break
                    continue
                fields = {h:normalize(v) for h,v in zip(headers,row)}
                if not fields.get(name_field):
                    continue
                if len(result) >= 20000:
                    raise ValueError('单次导入人才记录不得超过20000条')
                expressions = {h:v for h,v in zip(headers,raw) if isinstance(v,str) and v.startswith('=')}
                mapped = {key: None if fields.get(label) is None else str(fields[label]) for key,label in FIELDS.items()}
                mapped['name'] = str(fields[name_field])
                result.append(dict(id=str(uuid5(NAMESPACE_URL,f'talent:{source_id}:{sheet.title}:{number}')),
                    source_id=source_id,sheet_name=sheet.title,source_row=number,
                    raw_data_json=json.dumps(fields,ensure_ascii=False),formulas_json=json.dumps(expressions,ensure_ascii=False),**mapped))
        return result
    finally:
        values.close();formulas.close()
