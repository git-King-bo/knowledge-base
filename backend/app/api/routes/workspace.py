"""Structured personnel, durable jobs, lifecycle and personal conversation APIs."""
import csv
import io
import json
from pathlib import Path
from typing import Literal
from uuid import uuid4
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select, func, delete, or_, update, case, cast, Float
from sqlalchemy.orm import Session
from app.core.security import actor, audit, check_base, check_source, now, require_admin
from app.db.session import get_db
from app.db.models import (TalentModel, SourceIndexModel, ImportJobModel, TalentRevisionModel,
    SavedConversationModel, KnowledgeSourceModel, KnowledgeBaseModel, KnowledgeBaseSourceModel,
    KnowledgeChunkModel, KnowledgeChunkEmbeddingModel, ChunkTalentModel, TrashModel, AuditModel)
from app.services.talent_import import FIELDS
from app.services.import_jobs import enqueue, submit, reusable, job_schema

router=APIRouter()

def active_base(db,base_id,write=False):
    check_base(db,base_id,write=write)
    base=db.get(KnowledgeBaseModel,base_id)
    if not base:raise HTTPException(404,'知识库不存在')
    if base.status!='active':raise HTTPException(409,'知识库已归档')
    return base

@router.post('/imports/{knowledge_base_id}',status_code=202)
async def upload(knowledge_base_id:str,file:UploadFile=File(...),db:Session=Depends(get_db)):
    active_base(db,knowledge_base_id,True)
    filename=Path(file.filename or 'upload.txt').name
    if Path(filename).suffix.lower() not in {'.txt','.md','.markdown','.csv','.xlsx','.json','.docx','.pdf'}:
        raise HTTPException(400,'不支持此文件类型')
    raw=await file.read(20*1024*1024+1)
    if not raw or len(raw)>20*1024*1024:raise HTTPException(413,'文件不能为空或超过20MB')
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(submit,db,knowledge_base_id,filename,raw)

class ReuseRequest(BaseModel):
    sha256:str=Field(pattern=r'^[a-f0-9]{64}$')

@router.post('/imports/{knowledge_base_id}/reuse')
def reuse(knowledge_base_id:str,payload:ReuseRequest,db:Session=Depends(get_db)):
    active_base(db,knowledge_base_id,True)
    source=reusable(db,payload.sha256)
    if not source:return {'reused':False}
    # Only users already authorized for source data may use zero-byte reuse.
    check_source(db,source.id)
    from app.repositories.sqlite import KnowledgeIngestionRepository
    KnowledgeIngestionRepository(db).attach_source_to_base(knowledge_base_id,source.id)
    return {'reused':True,'source_id':source.id}

@router.get('/jobs')
def jobs(db:Session=Depends(get_db),knowledge_base_id:str|None=None):
    query=select(ImportJobModel).join(KnowledgeSourceModel,KnowledgeSourceModel.id==ImportJobModel.source_id)
    if knowledge_base_id:check_base(db,knowledge_base_id);query=query.where(ImportJobModel.source_id.in_(select(KnowledgeBaseSourceModel.source_id).where(KnowledgeBaseSourceModel.knowledge_base_id==knowledge_base_id)))
    return [job_schema(x) for x in db.scalars(query.order_by(ImportJobModel.created_at.desc()).limit(100))]

@router.post('/jobs/{job_id}/{action}')
def control_job(job_id:str,action:str,db:Session=Depends(get_db)):
    job=db.get(ImportJobModel,job_id)
    if not job:raise HTTPException(404,'任务不存在')
    check_source(db,job.source_id,True)
    if action=='cancel' and job.status in {'queued','running'}:
        job.cancel_requested=True
        if job.status=='queued':job.status='cancelled'
    elif action=='retry' and job.status in {'failed','cancelled'}:
        if db.scalar(select(ImportJobModel.id).where(ImportJobModel.source_id==job.source_id,ImportJobModel.status.in_(['queued','running']))):
            raise HTTPException(409,'已有任务正在处理此资料')
        job.status='queued';job.cancel_requested=False;job.error=None
    else:raise HTTPException(409,'当前任务状态不支持此操作')
    job.updated_at=now();db.commit();audit(db,'job.'+action,job_id)
    return job_schema(job)

@router.post('/indexes/{source_id}/rebuild',status_code=202)
def rebuild(source_id:str,knowledge_base_id:str,db:Session=Depends(get_db)):
    check_source(db,source_id,True);active_base(db,knowledge_base_id,True)
    if not db.scalar(select(KnowledgeBaseSourceModel.id).where(KnowledgeBaseSourceModel.source_id==source_id,KnowledgeBaseSourceModel.knowledge_base_id==knowledge_base_id)):
        raise HTTPException(404,'资料不属于该知识库')
    index=db.get(SourceIndexModel,source_id)
    if index:
        index.revision+=1;index.edited=True
    db.commit()
    return job_schema(enqueue(db,source_id,knowledge_base_id))


def talent_query(db,knowledge_base_id=None,q='',organization='',domain=''):
    query=select(TalentModel)
    if knowledge_base_id:
        check_base(db,knowledge_base_id)
        query=query.where(TalentModel.source_id.in_(select(KnowledgeBaseSourceModel.source_id).where(KnowledgeBaseSourceModel.knowledge_base_id==knowledge_base_id)))
    if q:query=query.where(or_(TalentModel.name.contains(q,autoescape=True),TalentModel.biography.contains(q,autoescape=True)))
    if organization:query=query.where(TalentModel.organization.contains(organization,autoescape=True))
    if domain:query=query.where(TalentModel.domain.contains(domain,autoescape=True))
    return query

def talent_order(sort_by, sort_order):
    if sort_by == 'openalex_h_index':
        text = func.trim(func.replace(TalentModel.openalex_h_index, ',', ''))
        value = case((text.regexp_match(r'^[0-9]+([.][0-9]+)?$'), cast(text, Float)), else_=None)
        return [value.is_(None), value.desc() if sort_order == 'desc' else value.asc(), TalentModel.name, TalentModel.id]
    return [TalentModel.name, TalentModel.id]

@router.get('/talents')
def talents(knowledge_base_id:str|None=None,q:str=Query('',max_length=100),organization:str=Query('',max_length=100),domain:str=Query('',max_length=100),
            page:int=Query(1,ge=1),page_size:int=Query(30,ge=1,le=100),
            sort_by:Literal['name','openalex_h_index']='name',sort_order:Literal['asc','desc']='asc',db:Session=Depends(get_db)):
    query=talent_query(db,knowledge_base_id,q,organization,domain)
    total=db.scalar(select(func.count()).select_from(query.subquery()))
    rows=db.scalars(query.order_by(*talent_order(sort_by,sort_order)).offset((page-1)*page_size).limit(page_size))
    keys=['openalex_h_index','id','name','organization','position','domain','location','source_id','sheet_name','source_row']
    return {'total':total,'page':page,'items':[{k:getattr(t,k) for k in keys} for t in rows]}

@router.get('/talents/export')
def export_talents(knowledge_base_id:str|None=None,q:str='',organization:str='',domain:str='',sort_by:Literal['name','openalex_h_index']='name',sort_order:Literal['asc','desc']='asc',db:Session=Depends(get_db)):
    output=io.StringIO();writer=csv.writer(output);writer.writerow(FIELDS.values())
    for talent in db.scalars(talent_query(db,knowledge_base_id,q,organization,domain).order_by(*talent_order(sort_by,sort_order)).limit(20000)):
        values=[getattr(talent,k) or '' for k in FIELDS]
        writer.writerow(["'"+v if v.startswith(('=','+','-','@','\t','\r')) else v for v in values])
    audit(db,'talent.export',knowledge_base_id or 'accessible')
    return Response('\ufeff'+output.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="talents.csv"'})

@router.get('/talents/duplicates')
def duplicate_talents(db:Session=Depends(get_db)):
    return [{'name':name,'count':count} for name,count in db.execute(select(TalentModel.name,func.count()).group_by(TalentModel.name).having(func.count()>1).limit(200))]

@router.get('/talents/{talent_id}')
def talent_detail(talent_id:str,db:Session=Depends(get_db)):
    talent=db.get(TalentModel,talent_id)
    if not talent:raise HTTPException(404,'人才不存在')
    check_source(db,talent.source_id)
    index=db.get(SourceIndexModel,talent.source_id)
    return {'id':talent.id,'fields':json.loads(talent.raw_data_json),'formulas':json.loads(talent.formulas_json),
            'source_id':talent.source_id,'sheet_name':talent.sheet_name,'source_row':talent.source_row,
            'revision':index.revision if index else 0,'indexed':bool(index and index.revision==index.indexed_revision)}

class TalentEdit(BaseModel):
    fields:dict[str,str|None]
    revision:int

@router.put('/talents/{talent_id}')
def edit_talent(talent_id:str,payload:TalentEdit,db:Session=Depends(get_db)):
    talent=db.get(TalentModel,talent_id)
    if not talent:raise HTTPException(404,'人才不存在')
    check_source(db,talent.source_id,True)
    # Shared sources cannot be edited by someone lacking write access to another linked base.
    links=list(db.scalars(select(KnowledgeBaseSourceModel).where(KnowledgeBaseSourceModel.source_id==talent.source_id)))
    for link in links:check_base(db,link.knowledge_base_id,True)
    if not links:raise HTTPException(409,'人才没有关联知识库')
    if len(json.dumps(payload.fields))>100000:raise HTTPException(413,'人才信息过长')
    fields=json.loads(talent.raw_data_json)
    if any(k not in fields and k not in FIELDS.values() for k in payload.fields):raise HTTPException(400,'不能添加未知字段')
    index=db.get(SourceIndexModel,talent.source_id)
    if not index:
        from app.services.import_jobs import fingerprint
        import hashlib
        source=db.get(KnowledgeSourceModel,talent.source_id)
        index=SourceIndexModel(source_id=talent.source_id,sha256=hashlib.sha256(Path(source.storage_path).read_bytes()).hexdigest(),fingerprint=fingerprint(),revision=0,indexed_revision=0,edited=False)
        db.add(index)
    if payload.revision!=index.revision:raise HTTPException(409,'资料已更新，请刷新后再编辑')
    db.add(TalentRevisionModel(id=str(uuid4()),talent_id=talent.id,user_id=actor.get().id if actor.get() else None,data_json=talent.raw_data_json,created_at=now()))
    fields.update(payload.fields)
    if not str(fields.get('姓名',talent.name) or '').strip():raise HTTPException(400,'姓名不能为空')
    talent.raw_data_json=json.dumps(fields,ensure_ascii=False)
    formulas=json.loads(talent.formulas_json)
    for label in payload.fields:formulas.pop(label,None)
    talent.formulas_json=json.dumps(formulas,ensure_ascii=False)
    for key,label in FIELDS.items():
        if label in fields:setattr(talent,key,None if fields[label] is None else str(fields[label]))
    db.flush()
    claimed=db.execute(update(SourceIndexModel).where(SourceIndexModel.source_id==talent.source_id,
        SourceIndexModel.revision==payload.revision).values(revision=payload.revision+1,edited=True))
    if claimed.rowcount!=1:
        db.rollback()
        raise HTTPException(409,'资料已被其他人更新，请刷新')
    db.commit();audit(db,'talent.updated',talent.id)
    job=enqueue(db,talent.source_id,links[0].knowledge_base_id)
    return {'ok':True,'job':job_schema(job)}

@router.get('/talents/{talent_id}/history')
def talent_history(talent_id:str,db:Session=Depends(get_db)):
    talent_detail(talent_id,db)
    return [{'id':x.id,'created_at':x.created_at,'fields':json.loads(x.data_json)} for x in db.scalars(select(TalentRevisionModel).where(TalentRevisionModel.talent_id==talent_id).order_by(TalentRevisionModel.created_at.desc()).limit(50))]

class Conversation(BaseModel):
    title:str=Field(max_length=160)
    messages:list[dict]=Field(max_length=100)
    favorite:bool=False
    feedback:str=Field('',max_length=1000)

def current_user_id():
    if not actor.get():raise HTTPException(400,'保存会话需要登录')
    return actor.get().id

@router.get('/conversations')
def conversations(db:Session=Depends(get_db)):
    return [{'id':x.id,'title':x.title,'favorite':x.favorite,'updated_at':x.updated_at} for x in db.scalars(select(SavedConversationModel).where(SavedConversationModel.user_id==current_user_id()).order_by(SavedConversationModel.updated_at.desc()).limit(100))]

@router.put('/conversations/{conversation_id}')
def save_conversation(conversation_id:str,payload:Conversation,db:Session=Depends(get_db)):
    uid=current_user_id()
    if len(conversation_id)>80:raise HTTPException(400,'会话ID过长')
    text=json.dumps(payload.messages,ensure_ascii=False)
    if len(text)>2_000_000:raise HTTPException(413,'会话超过保存大小限制')
    item=db.get(SavedConversationModel,conversation_id)
    if item and item.user_id!=uid:raise HTTPException(404,'会话不存在')
    for turn in payload.messages:
        base_id=(turn.get('request') or {}).get('knowledgeBaseId')
        if base_id:check_base(db,base_id)
    if not item:item=SavedConversationModel(id=conversation_id,user_id=uid);db.add(item)
    item.title=payload.title;item.messages_json=text;item.favorite=payload.favorite;item.feedback=payload.feedback;item.updated_at=now();db.commit()
    return {'id':item.id}

@router.get('/conversations/{conversation_id}')
def conversation(conversation_id:str,db:Session=Depends(get_db)):
    item=db.get(SavedConversationModel,conversation_id)
    if not item or item.user_id!=current_user_id():raise HTTPException(404,'会话不存在')
    messages=json.loads(item.messages_json)
    for turn in messages:
        base_id=(turn.get('request') or {}).get('knowledgeBaseId')
        if base_id:check_base(db,base_id)
    return {'title':item.title,'messages':messages,'favorite':item.favorite,'feedback':item.feedback}

@router.delete('/conversations/{conversation_id}')
def delete_conversation(conversation_id:str,db:Session=Depends(get_db)):
    conversation(conversation_id,db)
    db.delete(db.get(SavedConversationModel,conversation_id));db.commit()
    return {'ok':True}

@router.get('/trash')
def trash(db:Session=Depends(get_db)):
    require_admin()
    return [{'id':b.id,'name':b.name,'deleted_at':t.deleted_at} for b,t in db.execute(select(KnowledgeBaseModel,TrashModel).join(TrashModel))]

@router.post('/trash/{base_id}/restore')
def restore(base_id:str,db:Session=Depends(get_db)):
    require_admin();item=db.get(TrashModel,base_id)
    if not item:raise HTTPException(404,'回收站记录不存在')
    base=db.get(KnowledgeBaseModel,base_id);base.status=item.previous_status
    db.delete(item);db.commit();audit(db,'base.restored',base_id)
    return {'ok':True}

@router.delete('/trash/{base_id}')
def purge(base_id:str,db:Session=Depends(get_db)):
    require_admin()
    if not db.get(TrashModel,base_id):raise HTTPException(409,'请先移入回收站')
    source_ids=list(db.scalars(select(KnowledgeBaseSourceModel.source_id).where(KnowledgeBaseSourceModel.knowledge_base_id==base_id)))
    if db.scalar(select(ImportJobModel.id).where(ImportJobModel.source_id.in_(source_ids),ImportJobModel.status.in_(['running','queued']))):
        raise HTTPException(409,'请先取消相关导入任务')
    db.delete(db.get(KnowledgeBaseModel,base_id));db.flush()
    paths=[]
    for sid in source_ids:
        if db.scalar(select(KnowledgeBaseSourceModel.id).where(KnowledgeBaseSourceModel.source_id==sid)):continue
        source=db.get(KnowledgeSourceModel,sid)
        tids=select(TalentModel.id).where(TalentModel.source_id==sid)
        cids=select(KnowledgeChunkModel.id).where(KnowledgeChunkModel.source_id==sid)
        for model,condition in [(TalentRevisionModel,TalentRevisionModel.talent_id.in_(tids)),(ChunkTalentModel,ChunkTalentModel.chunk_id.in_(cids)),
            (KnowledgeChunkEmbeddingModel,KnowledgeChunkEmbeddingModel.chunk_id.in_(cids)),(TalentModel,TalentModel.source_id==sid),
            (SourceIndexModel,SourceIndexModel.source_id==sid),(ImportJobModel,ImportJobModel.source_id==sid)]:
            db.execute(delete(model).where(condition))
        paths.append(Path(source.storage_path));db.delete(source)
    db.commit()
    for path in paths:path.unlink(missing_ok=True)
    audit(db,'base.purged',base_id)
    return {'ok':True}

@router.get('/audit')
def audit_events(db:Session=Depends(get_db),page:int=Query(1,ge=1)):
    require_admin()
    return [{'id':x.id,'user_id':x.user_id,'action':x.action,'target':x.target,'detail':x.detail,'created_at':x.created_at} for x in db.scalars(select(AuditModel).order_by(AuditModel.created_at.desc()).offset((page-1)*50).limit(50))]

@router.get('/operations')
def operations(db:Session=Depends(get_db)):
    from app.core.observability import counts
    from app.db.models import RequestBudgetModel
    require_admin()
    return {'http':dict(counts),'jobs':dict(db.execute(select(ImportJobModel.status,func.count()).group_by(ImportJobModel.status)).all()),
            'budgets':[{'user_id':x.user_id,'day':x.day,'requests':x.requests,'tokens':x.tokens,'reserved':x.reserved} for x in db.scalars(select(RequestBudgetModel).where(RequestBudgetModel.day==now().date().isoformat()))]}

@router.post('/operations/backup')
def create_backup(db:Session=Depends(get_db)):
    require_admin()
    from scripts.backup_workspace import backup
    database=Path(db.get_bind().url.database).resolve()
    name=now().strftime('workspace-%Y%m%dT%H%M%S.tar.gz')
    path=database.parent/'storage/backups'/name
    backup(database,path)
    audit(db,'backup.created',name)
    return {'filename':name,'message':'备份已保存在服务器 storage/backups；加密主密钥需单独保管。'}

class DuplicateReview(BaseModel):
    talent_ids:list[str]=Field(min_length=2,max_length=20)
    decision:str=Field(pattern='^(distinct|needs_merge)$')
    note:str=Field('',max_length=1000)

@router.post('/talent-duplicate-reviews')
def review_duplicate(payload:DuplicateReview,db:Session=Depends(get_db)):
    for tid in payload.talent_ids:
        talent=db.get(TalentModel,tid)
        if not talent:raise HTTPException(404,'人才不存在')
        check_source(db,talent.source_id,True)
    audit(db,'talent.duplicate_review',','.join(payload.talent_ids)[:255],json.dumps(payload.model_dump(),ensure_ascii=False))
    return {'ok':True,'message':'已记录人工核对结果，原始记录保留。'}

@router.get('/orphan-sources')
def orphan_sources(db:Session=Depends(get_db)):
    require_admin()
    return [{'id':x.id,'filename':x.filename,'updated_at':x.updated_at} for x in db.scalars(select(KnowledgeSourceModel).where(
        ~KnowledgeSourceModel.id.in_(select(KnowledgeBaseSourceModel.source_id))).order_by(KnowledgeSourceModel.updated_at).limit(200))]

@router.delete('/orphan-sources/{source_id}')
def purge_orphan(source_id:str,db:Session=Depends(get_db)):
    require_admin()
    if db.scalar(select(KnowledgeBaseSourceModel.id).where(KnowledgeBaseSourceModel.source_id==source_id)):
        raise HTTPException(409,'资料仍被知识库使用')
    if db.scalar(select(ImportJobModel.id).where(ImportJobModel.source_id==source_id,ImportJobModel.status.in_(['running','queued']))):
        raise HTTPException(409,'请先取消相关任务')
    source=db.get(KnowledgeSourceModel,source_id)
    if not source:raise HTTPException(404,'资料不存在')
    tids=select(TalentModel.id).where(TalentModel.source_id==source_id)
    cids=select(KnowledgeChunkModel.id).where(KnowledgeChunkModel.source_id==source_id)
    for model,condition in [(TalentRevisionModel,TalentRevisionModel.talent_id.in_(tids)),(ChunkTalentModel,ChunkTalentModel.chunk_id.in_(cids)),
        (KnowledgeChunkEmbeddingModel,KnowledgeChunkEmbeddingModel.chunk_id.in_(cids)),(TalentModel,TalentModel.source_id==source_id),
        (SourceIndexModel,SourceIndexModel.source_id==source_id),(ImportJobModel,ImportJobModel.source_id==source_id)]:
        db.execute(delete(model).where(condition))
    path=Path(source.storage_path);db.delete(source);db.commit();path.unlink(missing_ok=True)
    audit(db,'source.purged',source_id)
    return {'ok':True}

@router.post('/imports/{knowledge_base_id}/preview')
async def preview_import(knowledge_base_id:str,file:UploadFile=File(...),db:Session=Depends(get_db)):
    active_base(db,knowledge_base_id,True)
    raw=await file.read(20*1024*1024+1)
    filename=Path(file.filename or 'upload.txt').name
    if not raw or len(raw)>20*1024*1024:raise HTTPException(413,'文件不能为空或超过20MB')
    if Path(filename).suffix.lower() not in {'.txt','.md','.markdown','.csv','.xlsx','.json','.docx','.pdf'}:
        raise HTTPException(400,'不支持此文件类型')
    from starlette.concurrency import run_in_threadpool
    def inspect():
        import tempfile,subprocess,sys
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/filename;path.write_bytes(raw)
            result=subprocess.run([sys.executable,'-m','app.services.parse_worker',str(path),filename,'preview'],capture_output=True,text=True,timeout=60)
            data=json.loads(result.stdout) if result.stdout.strip() else {'error':'文件无法解析'}
            if result.returncode or data.get('error'):raise HTTPException(400,data.get('error','文件无法解析'))
            people=data['talents']
            names=[r['name'] for r in people]
            return {'filename':filename,'characters':len(data['text']),'talent_records':len(people),
                    'duplicate_name_rows':len(names)-len(set(names)),
                    'fields':list(json.loads(people[0]['raw_data_json'])) if people else [],
                    'sample':[json.loads(p['raw_data_json']) for p in people[:3]]}
    return await run_in_threadpool(inspect)
