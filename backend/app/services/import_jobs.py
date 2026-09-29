"""Durable single-worker queue. File bytes are verified before authorized reuse."""
import hashlib
import json
import logging
from pathlib import Path
import subprocess
import sys
import threading
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, func, delete
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.security import now, actor
from app.db.models import (KnowledgeSourceModel, KnowledgeChunkModel, KnowledgeChunkEmbeddingModel,
    SourceIndexModel, ImportJobModel, TalentModel, ChunkTalentModel, KnowledgeBaseSourceModel)
from app.db.session import SessionLocal
from app.repositories.sqlite import KnowledgeIngestionRepository
from app.services.embeddings import EmbeddingClient
from app.services.ingestion import split_into_chunks

log=logging.getLogger(__name__)
submission_lock=threading.Lock()

class StaleRevision(RuntimeError):
    pass

def fingerprint():
    return hashlib.sha256(json.dumps({'parser':'v2','chunk':settings.knowledge_chunk_max_chars,
        'overlap':settings.knowledge_chunk_overlap_chars,'embedding_url':settings.embedding_api_url,
        'embedding_model':settings.embedding_model},sort_keys=True).encode()).hexdigest()


def job_schema(job):
    return {key:getattr(job,key) for key in ['id','source_id','base_id','status','stage','completed','total','attempts','error','cancel_requested','created_at','updated_at']}


def reusable(db, digest):
    # Scoped Source query prevents hash probing across inaccessible knowledge bases.
    candidates=db.scalars(select(KnowledgeSourceModel).join(SourceIndexModel).where(
        SourceIndexModel.sha256==digest, SourceIndexModel.fingerprint==fingerprint(),
        SourceIndexModel.edited.is_(False),SourceIndexModel.revision==SourceIndexModel.indexed_revision,
        KnowledgeSourceModel.status=='parsed')).all()
    for source in candidates:
        if Path(source.storage_path).is_file() and not source.error_message:
            return source
    return None


def enqueue(db, source_id, base_id, *, stage='queued'):
    existing=db.scalar(select(ImportJobModel).where(ImportJobModel.source_id==source_id,
        ImportJobModel.status.in_(['queued','running'])))
    if existing:return existing
    user=actor.get()
    job=ImportJobModel(id=str(uuid4()), source_id=source_id,base_id=base_id,user_id=user.id if user else None,
        status='queued',stage=stage,completed=0,total=0,attempts=0,cancel_requested=False,created_at=now(),updated_at=now())
    db.add(job);db.commit();db.refresh(job)
    return job


def submit(db, base_id, filename, raw):
    digest=hashlib.sha256(raw).hexdigest()
    with submission_lock:
        repo=KnowledgeIngestionRepository(db)
        found=reusable(db,digest)
        if found:
            repo.attach_source_to_base(base_id,found.id)
            return {'reused':True,'source_id':found.id,'job':None}
        if db.scalar(select(func.count()).select_from(ImportJobModel).where(ImportJobModel.status.in_(['queued','running'])))>=settings.max_pending_jobs:
            raise HTTPException(429,'待处理任务已满，请稍后重试')
        # A pending duplicate shares the same durable job.
        pending=db.execute(select(KnowledgeSourceModel,ImportJobModel).join(SourceIndexModel).join(ImportJobModel,
            ImportJobModel.source_id==KnowledgeSourceModel.id).where(SourceIndexModel.sha256==digest,
            SourceIndexModel.fingerprint==fingerprint(), ImportJobModel.status.in_(['queued','running']))).first()
        if pending:
            repo.attach_source_to_base(base_id,pending[0].id)
            return {'reused':False,'source_id':pending[0].id,'job':job_schema(pending[1])}
        root=Path(settings.upload_dir);root.mkdir(parents=True,exist_ok=True)
        path=root/f'{uuid4()}-{Path(filename).name}'
        path.write_bytes(raw)
        source=repo.create_source(filename=Path(filename).name,mime_type='application/octet-stream',storage_path=str(path),content_text='')
        repo.attach_source_to_base(base_id,source.id)
        db.add(SourceIndexModel(source_id=source.id,sha256=digest,fingerprint=fingerprint(),revision=1,indexed_revision=0,edited=False))
        db.commit()
        job=enqueue(db,source.id,base_id)
        return {'reused':False,'source_id':source.id,'job':job_schema(job)}


def process_job(db,job):
    repo=KnowledgeIngestionRepository(db)
    source=db.get(KnowledgeSourceModel,job.source_id)
    if not source:raise ValueError('源文件不存在')
    index=db.get(SourceIndexModel,source.id)
    starting_revision=index.revision if index else 1
    def checkpoint(stage,completed=0,total=0):
        db.refresh(job)
        if job.cancel_requested:raise InterruptedError('任务已取消')
        if index:
            db.refresh(index)
            if index.revision!=starting_revision:raise StaleRevision('处理中资料已更新，已重新排队')
        job.stage=stage;job.completed=completed;job.total=total;job.updated_at=now();db.commit()
    checkpoint('parsing')
    # Resume from persisted chunks unless source edits require a fresh text index.
    talents=list(db.scalars(select(TalentModel).where(TalentModel.source_id==source.id).order_by(TalentModel.sheet_name,TalentModel.source_row)))
    stale=bool(index and index.indexed_revision!=index.revision and index.edited)
    existing_chunks=repo.list_chunks(source_id=source.id)
    if not existing_chunks or stale:
        if not talents:
            result=subprocess.run([sys.executable,'-m','app.services.parse_worker',str(Path(source.storage_path).resolve()),source.filename,source.id],
                capture_output=True,text=True,timeout=240 if settings.ocr_enabled else 60)
            parsed=json.loads(result.stdout) if result.stdout.strip() else {'error':'解析进程失败'}
            if result.returncode or parsed.get('error'):raise ValueError(parsed.get('error','解析失败'))
            repo.update_source_text(source.id,content_text=parsed['text'],mime_type=parsed['mime_type'])
            for record in parsed['talents']:
                if not db.get(TalentModel,record['id']):db.add(TalentModel(**record,created_at=now()))
            db.commit()
            talents=list(db.scalars(select(TalentModel).where(TalentModel.source_id==source.id).order_by(TalentModel.sheet_name,TalentModel.source_row)))
        drafts=[];owners=[]
        if talents:
            for talent in talents:
                fields=json.loads(talent.raw_data_json)
                text='\n'.join(f'{k}：{v}' for k,v in fields.items() if v is not None)
                for chunk in split_into_chunks(text,max_chars=settings.knowledge_chunk_max_chars,overlap=settings.knowledge_chunk_overlap_chars):
                    drafts.append({'chunk_index':len(drafts),'title':talent.name,'content':chunk.content,'token_count':chunk.token_count,'vector':chunk.vector})
                    owners.append(talent.id)
            repo.update_source_text(source.id,content_text='\n\n'.join(json.dumps(json.loads(t.raw_data_json),ensure_ascii=False) for t in talents))
        else:
            for chunk in split_into_chunks(source.content_text,max_chars=settings.knowledge_chunk_max_chars,overlap=settings.knowledge_chunk_overlap_chars):
                drafts.append({'chunk_index':chunk.chunk_index,'title':source.filename,'content':chunk.content,'token_count':chunk.token_count,'vector':chunk.vector})
        old_ids=select(KnowledgeChunkModel.id).where(KnowledgeChunkModel.source_id==source.id)
        db.execute(delete(ChunkTalentModel).where(ChunkTalentModel.chunk_id.in_(old_ids)));db.commit()
        existing_chunks=repo.replace_chunks(source.id,drafts)
        for chunk,talent_id in zip(existing_chunks,owners):db.add(ChunkTalentModel(chunk_id=chunk.id,talent_id=talent_id))
        db.commit()
    checkpoint('embedding',0,len(existing_chunks))
    client=EmbeddingClient(db=db,knowledge_base_id=job.base_id)
    if client.enabled:
        ready=set(db.scalars(select(KnowledgeChunkEmbeddingModel.chunk_id).where(KnowledgeChunkEmbeddingModel.embedding_model==settings.embedding_model)))
        pending=[c for c in existing_chunks if c.id not in ready]
        done=len(existing_chunks)-len(pending)
        for start in range(0,len(pending),max(1,settings.embedding_batch_size)):
            checkpoint('embedding',done,len(existing_chunks))
            batch=pending[start:start+max(1,settings.embedding_batch_size)]
            from app.core.limits import embed_with_budget
            vectors=embed_with_budget(db,job,client,[c.content for c in batch])
            repo.replace_chunk_embeddings(list(zip([c.id for c in batch],vectors,strict=True)),embedding_model=settings.embedding_model)
            done+=len(batch)
    checkpoint('complete',len(existing_chunks),len(existing_chunks))
    if index:index.indexed_revision=starting_revision;index.fingerprint=fingerprint()
    repo.set_source_error_message(source.id,None)
    job.status='done';job.error=None;job.updated_at=now();db.commit()


class Worker:
    def __init__(self):
        self.stop=threading.Event();self.thread=None;self.lock_file=None
    def start(self):
        # One worker per SQLite deployment, including across reloads/processes.
        import fcntl
        root=Path(settings.upload_dir).parent;root.mkdir(parents=True,exist_ok=True)
        self.lock_file=(root/'worker.lock').open('a')
        try:fcntl.flock(self.lock_file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:self.lock_file.close();self.lock_file=None;return
        with SessionLocal() as db:
            for job in db.scalars(select(ImportJobModel).where(ImportJobModel.status=='running')):
                job.status='queued';job.updated_at=now()
            db.commit()
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
    def run(self):
        while not self.stop.is_set():
            try:
                with SessionLocal() as db:
                    job=db.scalar(select(ImportJobModel).where(ImportJobModel.status=='queued').order_by(ImportJobModel.created_at).limit(1))
                    if job:
                        job.status='running';job.attempts+=1;job.updated_at=now();db.commit()
                        try:process_job(db,job)
                        except Exception as exc:
                            db.rollback();db.refresh(job)
                            job.status='queued' if isinstance(exc,StaleRevision) else 'cancelled' if isinstance(exc,InterruptedError) else 'failed'
                            job.error=str(exc)[:500];job.updated_at=now()
                            source=db.get(KnowledgeSourceModel,job.source_id)
                            if source:source.error_message=job.error
                            db.commit();log.warning('import_failed job=%s type=%s',job.id,type(exc).__name__)
                        continue
            except Exception:
                log.exception('worker_iteration_failed')
            self.stop.wait(1)
    def close(self):
        self.stop.set()
        if self.thread:self.thread.join(timeout=2)
        # File lock remains held until the active worker exits or process terminates.
        if self.lock_file and (not self.thread or not self.thread.is_alive()):self.lock_file.close()
