"""Resumable local staging; published chunks are untouched until all vectors exist."""
import hashlib
import json
import math
import os
from pathlib import Path
from time import sleep
import time
from app.core.config import settings


def stage_embeddings(db,job,client,drafts,revision,fingerprint,checkpoint,*,reuse=None):
    if not client.enabled:return None
    root=Path(settings.upload_dir).parent/'index-staging'
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    path=root/f'{job.id}-{revision}-{fingerprint[:16]}.jsonl'
    hashes=[hashlib.sha256(d['content'].encode()).hexdigest() for d in drafts]
    done=0;dimension=None
    if path.exists():
        with path.open('r+b') as handle:
            while True:
                position=handle.tell();line=handle.readline()
                if not line:break
                try:
                    row=json.loads(line);vector=row['vector']
                    if done>=len(hashes) or row['hash']!=hashes[done] or not valid_vector(vector,dimension):raise ValueError('Invalid staged vector')
                    dimension=len(vector);done+=1
                except (ValueError,KeyError,TypeError):
                    handle.truncate(position);break
    from app.core.limits import embed_with_budget
    width=max(1,min(settings.embedding_batch_size,8))
    with path.open('a',encoding='utf-8') as handle:
        path.chmod(0o600)
        for start in range(done,len(drafts),width):
            checkpoint('embedding',start,len(drafts))
            batch=drafts[start:start+width]
            from sqlalchemy import select
            from app.db.models import KnowledgeChunkEmbeddingModel
            ids=[reuse[h] for h in hashes[start:start+len(batch)] if reuse and h in reuse]
            cached=dict(db.execute(select(KnowledgeChunkEmbeddingModel.chunk_id,KnowledgeChunkEmbeddingModel.embedding_json).where(
                KnowledgeChunkEmbeddingModel.chunk_id.in_(ids))).all()) if ids else {}
            vectors=[];missing=[]
            for offset,draft in enumerate(batch,start):
                raw=cached.get((reuse or {}).get(hashes[offset]))
                try:vector=json.loads(raw) if raw else None
                except ValueError:vector=None
                if not valid_vector(vector,dimension) or settings.embedding_dimensions and len(vector)!=settings.embedding_dimensions:
                    vector=None;missing.append(offset-start)
                vectors.append(vector)
            if missing:
                generated=embed_with_budget(db,job,client,[batch[i]['content'] for i in missing])
                if len(generated)!=len(missing):raise ValueError('Embedding batch length mismatch')
                for i,vector in zip(missing,generated,strict=True):vectors[i]=vector
            for offset,vector in enumerate(vectors,start):
                if not valid_vector(vector,dimension):raise ValueError('Embedding dimensions/values are invalid')
                if settings.embedding_dimensions and len(vector)!=settings.embedding_dimensions:raise ValueError('Embedding dimensions differ from configuration')
                dimension=len(vector)
                handle.write(json.dumps({'hash':hashes[offset],'vector':vector},separators=(',',':'))+'\n')
            handle.flush()
            os.fsync(handle.fileno())
            if missing and settings.embedding_index_pause:sleep(settings.embedding_index_pause)
    return path


def valid_vector(vector,dimension=None):
    return isinstance(vector,list) and bool(vector) and (dimension is None or len(vector)==dimension) and all(
        isinstance(v,(int,float)) and math.isfinite(v) for v in vector) and sum(v*v for v in vector)>0


def read_vectors(path):
    with path.open(encoding='utf-8') as handle:
        for line in handle:yield json.loads(line)['vector']


def cleanup_staging(db):
    from app.db.models import ImportJobModel
    root=Path(settings.upload_dir).parent/'index-staging'
    size=0
    for path in sorted(root.glob('*.jsonl'),key=lambda p:p.stat().st_mtime,reverse=True):
        info=path.stat();size+=info.st_size
        job=db.get(ImportJobModel,path.name[:36])
        if not job or job.status in ('done','cancelled') or (job.status=='failed' and (
                time.time()-info.st_mtime>7*86400 or size>512*1024*1024)):
            path.unlink(missing_ok=True)
