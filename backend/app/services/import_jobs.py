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
from sqlalchemy import select, func, delete, update
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.security import now, actor
from app.db.models import (KnowledgeSourceModel, KnowledgeChunkModel, KnowledgeChunkEmbeddingModel,
    SourceIndexModel, ImportJobModel, TalentModel, ChunkTalentModel, KnowledgeBaseSourceModel,KnowledgeBaseModel,TrashModel)
from app.db.session import SessionLocal
from app.repositories.sqlite import KnowledgeIngestionRepository
from app.services.embeddings import EmbeddingClient
from app.services.ingestion import split_into_chunks

log=logging.getLogger(__name__)
submission_lock=threading.Lock()

class StaleRevision(RuntimeError):
    pass

def fingerprint():
    from app.services.talent_documents import VERSION
    data={'parser':'v5-field-children-atomic','documents':VERSION,'chunk':settings.knowledge_chunk_max_chars,
        'overlap':settings.knowledge_chunk_overlap_chars,'embedding_url':settings.embedding_api_url,
        'embedding_model':settings.embedding_model,'embedding_dimensions':settings.embedding_dimensions}
    if settings.embedding_revision:data['embedding_revision']=settings.embedding_revision
    return hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()


def compatible_embedding_fingerprints():
    # v4's digest proves the same endpoint/model/dimensions. Only identical
    # document hashes may reuse its vectors, never old models or changed text.
    result={fingerprint()}
    if not settings.embedding_revision:
        old={'parser':'v4-field-children-atomic','chunk':settings.knowledge_chunk_max_chars,
            'overlap':settings.knowledge_chunk_overlap_chars,'embedding_url':settings.embedding_api_url,
            'embedding_model':settings.embedding_model,'embedding_dimensions':settings.embedding_dimensions}
        result.add(hashlib.sha256(json.dumps(old,sort_keys=True).encode()).hexdigest())
    return result


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
    job.index_fingerprint=fingerprint()
    db.add(job);db.commit();db.refresh(job)
    return job


def talent_index_incomplete(db, source_id):
    """A vector count alone cannot establish usable record-level coverage."""
    talents = db.scalar(select(func.count()).select_from(TalentModel).where(TalentModel.source_id == source_id))
    if not talents:
        return False
    chunks = db.scalar(select(func.count()).select_from(KnowledgeChunkModel).where(KnowledgeChunkModel.source_id == source_id))
    owned, people = db.execute(select(func.count(ChunkTalentModel.chunk_id), func.count(func.distinct(ChunkTalentModel.talent_id)))
        .join(KnowledgeChunkModel, KnowledgeChunkModel.id == ChunkTalentModel.chunk_id)
        .join(TalentModel, TalentModel.id == ChunkTalentModel.talent_id)
        .where(KnowledgeChunkModel.source_id == source_id, TalentModel.source_id == source_id)).one()
    return chunks == 0 or owned != chunks or people != talents


def embedding_index_incomplete(db,source_id):
    if not settings.embedding_api_url:return False
    count=db.scalar(select(func.count()).select_from(KnowledgeChunkModel).where(KnowledgeChunkModel.source_id==source_id))
    query=select(func.count()).select_from(KnowledgeChunkEmbeddingModel).join(KnowledgeChunkModel).where(
        KnowledgeChunkModel.source_id==source_id,KnowledgeChunkEmbeddingModel.embedding_model==settings.embedding_model)
    if settings.embedding_dimensions:query=query.where(KnowledgeChunkEmbeddingModel.embedding_dim==settings.embedding_dimensions)
    return not count or db.scalar(query)!=count


def queue_index_repairs(db):
    """Idempotently schedule legacy ownership repairs; failed jobs need explicit retry."""
    pending = db.scalar(select(func.count()).select_from(ImportJobModel).where(ImportJobModel.status.in_(['queued','running'])))
    active=select(KnowledgeBaseSourceModel.source_id).join(KnowledgeBaseModel).where(
        KnowledgeBaseModel.status=='active',~KnowledgeBaseModel.id.in_(select(TrashModel.base_id)))
    sources = db.scalars(select(KnowledgeSourceModel).where(KnowledgeSourceModel.status == 'parsed',KnowledgeSourceModel.id.in_(active)))
    for source in list(sources):
        if pending >= settings.max_pending_jobs:
            break
        index=db.get(SourceIndexModel,source.id)
        if not talent_index_incomplete(db, source.id) and not embedding_index_incomplete(db,source.id) and index and index.fingerprint==fingerprint() and index.revision==index.indexed_revision:
            continue
        from sqlalchemy import or_,and_
        existing = db.scalar(select(ImportJobModel.id).where(ImportJobModel.source_id == source.id,
            or_(ImportJobModel.status.in_(['queued','running']),and_(ImportJobModel.status.in_(['failed','cancelled']),
                ImportJobModel.index_fingerprint==fingerprint()))))
        if existing:
            continue
        base_id = db.scalar(select(KnowledgeBaseSourceModel.knowledge_base_id).join(KnowledgeBaseModel).where(
            KnowledgeBaseSourceModel.source_id == source.id,KnowledgeBaseModel.status=='active',~KnowledgeBaseModel.id.in_(select(TrashModel.base_id))))
        if base_id:
            enqueue(db, source.id, base_id, stage='repair_record_index')
            pending += 1


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
    if index is None:
        path=Path(source.storage_path)
        digest=hashlib.sha256(path.read_bytes() if path.is_file() else source.content_text.encode()).hexdigest()
        index=SourceIndexModel(source_id=source.id,sha256=digest,fingerprint='',revision=1,indexed_revision=0,edited=False)
        db.add(index);db.commit()
    starting_revision=index.revision
    job.index_fingerprint=fingerprint()
    def checkpoint(stage,completed=0,total=0):
        db.refresh(job)
        if job.cancel_requested:raise InterruptedError('任务已取消')
        if index:
            db.refresh(index)
            if index.revision!=starting_revision:raise StaleRevision('处理中资料已更新，已重新排队')
        job.stage=stage;job.completed=completed;job.total=total;job.updated_at=now();db.commit()
    checkpoint('parsing')
    talents=list(db.scalars(select(TalentModel).where(TalentModel.source_id==source.id).order_by(TalentModel.sheet_name,TalentModel.source_row)))
    if not talents and (not source.content_text or Path(source.filename).suffix.lower()=='.xlsx'):
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
        from app.services.talent_documents import field_chunks
        for talent in talents:
            for draft in field_chunks(json.loads(talent.raw_data_json),max_chars=settings.knowledge_chunk_max_chars,overlap=settings.knowledge_chunk_overlap_chars):
                draft['chunk_index']=len(drafts);drafts.append(draft);owners.append(talent.id)
    else:
        for chunk in split_into_chunks(source.content_text,max_chars=settings.knowledge_chunk_max_chars,overlap=settings.knowledge_chunk_overlap_chars):
            drafts.append({'chunk_index':chunk.chunk_index,'title':source.filename,'content':chunk.content,'token_count':chunk.token_count,'vector':chunk.vector})
    if not drafts:raise ValueError('没有可索引的内容')
    client=EmbeddingClient(db=db,knowledge_base_id=job.base_id)
    from app.services.index_staging import stage_embeddings,read_vectors
    reuse={}
    if index.fingerprint in compatible_embedding_fingerprints():
        statement=select(KnowledgeChunkModel.content,KnowledgeChunkEmbeddingModel.chunk_id).join(KnowledgeChunkEmbeddingModel).where(
            KnowledgeChunkModel.source_id==source.id,KnowledgeChunkEmbeddingModel.embedding_model==settings.embedding_model)
        if settings.embedding_dimensions:statement=statement.where(KnowledgeChunkEmbeddingModel.embedding_dim==settings.embedding_dimensions)
        for content,chunk_id in db.execute(statement).yield_per(128):reuse[hashlib.sha256(content.encode()).hexdigest()]=chunk_id
    staged=stage_embeddings(db,job,client,drafts,starting_revision,fingerprint(),checkpoint,reuse=reuse)
    checkpoint('publishing',len(drafts),len(drafts))
    # Version fence and all index replacements share ONE transaction. Failure,
    # cancellation or an edit keeps the previously published index intact.
    try:
        fence=db.execute(update(SourceIndexModel).where(SourceIndexModel.source_id==source.id,SourceIndexModel.revision==starting_revision)
            .values(indexed_revision=starting_revision,fingerprint=fingerprint()))
        if fence.rowcount!=1:raise StaleRevision('处理中资料已更新，已重新排队')
        old_ids=select(KnowledgeChunkModel.id).where(KnowledgeChunkModel.source_id==source.id)
        db.execute(delete(ChunkTalentModel).where(ChunkTalentModel.chunk_id.in_(old_ids)))
        chunks=repo.replace_chunks(source.id,drafts,commit=False)
        for chunk,talent_id in zip(chunks,owners):db.add(ChunkTalentModel(chunk_id=chunk.id,talent_id=talent_id))
        if staged:
            from itertools import islice
            vectors=read_vectors(staged)
            for start in range(0,len(chunks),100):
                batch=chunks[start:start+100];part=list(islice(vectors,len(batch)))
                if len(part)!=len(batch):raise ValueError('Staged index is incomplete')
                repo.replace_chunk_embeddings(list(zip([c.id for c in batch],part,strict=True)),embedding_model=settings.embedding_model,commit=False)
        changed=db.execute(update(ImportJobModel).where(ImportJobModel.id==job.id,ImportJobModel.cancel_requested.is_(False)).values(
            status='done',stage='complete',completed=len(chunks),total=len(chunks),error=None,updated_at=now()))
        if changed.rowcount!=1:raise InterruptedError('任务已取消')
        db.commit()
    except Exception:
        db.rollback();raise
    if staged:staged.unlink(missing_ok=True)
    db.refresh(job)


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
            from app.services.index_staging import cleanup_staging
            cleanup_staging(db)
            for job in db.scalars(select(ImportJobModel).where(ImportJobModel.status=='running')):
                job.status='queued';job.updated_at=now()
            db.commit()
            queue_index_repairs(db)
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
                            if isinstance(exc,(StaleRevision,InterruptedError)):
                                root=Path(settings.upload_dir).parent/'index-staging'
                                for path in root.glob(f'{job.id}-*.jsonl'):path.unlink(missing_ok=True)
                        if job.status=='done':queue_index_repairs(db)
                        continue
            except Exception:
                log.exception('worker_iteration_failed')
            self.stop.wait(1)
    def close(self, wait_seconds=2):
        self.stop.set()
        if self.thread:self.thread.join(timeout=wait_seconds)
        # File lock remains held until the active worker exits or process terminates.
        if self.lock_file and (not self.thread or not self.thread.is_alive()):self.lock_file.close()
