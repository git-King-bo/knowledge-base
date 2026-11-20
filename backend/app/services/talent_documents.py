"""Field-aware child chunks with a single talent owner and source field label."""
from app.services.ingestion import split_into_chunks, _tokenize, _vectorize

VERSION='field-children-v2'
SEARCH_FIELDS=('领域','未来产业方向','细分关键词','研究方向','技术角色定位','当前职务','所在国家／城市',
    '详细个人简介','个人简介','代表成果','创业／项目经历','工作经历','教育经历','公开观点','开源资产摘要','深度调研文档')
PRIVATE_FIELDS=('联系','电话','邮箱','email','手机','微信','证件','身份证','护照','银行卡','密码','密钥','secret','token','password','api_key','authorization','access_key',
    '操作记录','运营记录','变化摘要','变更摘要','更新结果','更新时间','待人工确认')


def public_fields(fields):
    return {f:v for f,v in fields.items() if not any(word in f.casefold() for word in PRIVATE_FIELDS)}


def field_chunks(fields, *, max_chars=480, overlap=80):
    # Identity is repeated for context, never another person's text. Contacts,
    # edit logs and operator notes stay in the source, outside model inputs.
    name=next((v for f,v in fields.items() if f.casefold() in ('姓名','name','full name','人员姓名','员工姓名')),None)
    identity='\n'.join(f'{f}：{str(v)[:80]}' for f,v in (('姓名',name),('当前机构',fields.get('当前机构'))) if v)
    allowed=public_fields(fields)
    names=set(f for f in fields if f.casefold() in ('姓名','name','full name','人员姓名','员工姓名'))
    ordered=list(dict.fromkeys(SEARCH_FIELDS+tuple(f for f in allowed if f not in names and f!='当前机构')))
    drafts=[]
    for field in ordered:
        if field not in allowed:continue
        if fields.get(field) is None or not str(fields[field]).strip():continue
        prefix=identity+'\n字段：'+field+'\n'
        width=max(100,max_chars-len(prefix))
        for part in split_into_chunks(str(fields[field]),max_chars=width,overlap=min(overlap,width//3)):
            content=prefix+part.content
            drafts.append({'chunk_index':len(drafts),'title':str(fields.get('姓名',''))[:255] or None,
                'content':content,'token_count':len(_tokenize(content)),'vector':_vectorize(content)})
    if not drafts:
        content=identity or '空的人才记录'
        drafts=[{'chunk_index':0,'title':str(fields.get('姓名',''))[:255] or None,'content':content,
                 'token_count':len(_tokenize(content)),'vector':_vectorize(content)}]
    return drafts
