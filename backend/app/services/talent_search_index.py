"""Bounded asynchronous vector loading. Request threads never fetch vector bodies.

Only source IDs authorized by the request are loaded. Each worker owns its DB
session; caches include database, source revisions, provider and model identity.
"""
from concurrent.futures import ThreadPoolExecutor,TimeoutError as FutureTimeout
from threading import Lock
from time import monotonic
import hashlib
import json
import numpy as np
from pathlib import Path
import os
import tempfile
import time
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db.models import KnowledgeChunkModel as Chunk, KnowledgeChunkEmbeddingModel as Embedding, ChunkTalentModel, SourceIndexModel
from app.services.query_cache import BoundedCache

_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='talent-index')
_cache = BoundedCache(max_bytes=128*1024*1024, max_entries=8, ttl=120)
_pending = {}
_lock = Lock()


def artifact_path(db, sheets, version='person-v1',generation=None):
    # Content identity includes ownership and every business field. Updated source
    # text, model, endpoint or database select a different immutable artifact.
    identity=(str(db.get_bind().url),settings.embedding_api_url,settings.embedding_model,version,
        [(s.source_id,s.sheet,s.rows) for s in sheets])
    if generation is not None:identity=identity+(generation,)
    digest=hashlib.sha256(json.dumps(identity,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()
    return Path(settings.upload_dir).parent/'search-index'/f'{digest}.npz'


def _load(engine, source_ids, model, artifact=None, allowed_ids=None):
    if artifact and artifact.is_file():
        try:
            with np.load(artifact,allow_pickle=False) as data:
                ids=data['ids'].tolist();matrix=data['matrix'].astype(np.float32)
                texts=data['texts'].tolist() if 'texts' in data else None
            if (matrix.ndim==2 and matrix.shape[0]==len(ids)
                    and set(ids)==allowed_ids and np.isfinite(matrix).all()
                    and np.all(np.linalg.norm(matrix,axis=1)>0)
                    and (model!=settings.embedding_model or not settings.embedding_dimensions or matrix.shape[1]==settings.embedding_dimensions)):
                matrix/=np.maximum(np.linalg.norm(matrix,axis=1,keepdims=True),1e-12)
                return (ids,matrix,texts) if texts is not None and len(texts)==len(ids) else (ids,matrix)
        except (OSError, ValueError, KeyError):
            pass  # An incomplete/corrupt local artifact must not disable DB fallback.
    with Session(engine) as db:
        from app.services.import_jobs import fingerprint
        stale = select(SourceIndexModel.source_id).where(SourceIndexModel.edited.is_(True), SourceIndexModel.revision != SourceIndexModel.indexed_revision)
        current=select(SourceIndexModel.source_id).where(SourceIndexModel.fingerprint==fingerprint(),SourceIndexModel.revision==SourceIndexModel.indexed_revision)
        statement=(select(ChunkTalentModel.talent_id, Embedding.embedding_json,Chunk.content)
            .join(Chunk, Chunk.id == ChunkTalentModel.chunk_id)
            .join(Embedding, Embedding.chunk_id == Chunk.id)
            .where(Chunk.source_id.in_(source_ids),Chunk.source_id.in_(current), ~Chunk.source_id.in_(stale), Embedding.embedding_model == model))
        if allowed_ids is not None:statement=statement.where(ChunkTalentModel.talent_id.in_(allowed_ids))
        rows=db.execute(statement).yield_per(128)
        ids=[]; vectors=[]; texts=[]; dimension=settings.embedding_dimensions if model==settings.embedding_model else None
        for person, raw,content in rows:
            try:vector=np.asarray(json.loads(raw), dtype=np.float32)
            except (ValueError,TypeError):continue
            if vector.ndim != 1 or not len(vector) or not np.isfinite(vector).all() or np.linalg.norm(vector)<=0:continue
            if dimension is None:dimension=len(vector)
            if len(vector)!=dimension:continue
            if len(ids)>=settings.talent_index_max_vectors:raise ValueError('Local vector index exceeds configured capacity')
            ids.append(person); vectors.append(vector);texts.append(content)
    if not vectors:
        return ids, np.empty((0, 0),dtype=np.float32)
    matrix=np.stack(vectors)
    matrix/=np.maximum(np.linalg.norm(matrix,axis=1,keepdims=True),1e-12)
    if artifact and set(ids)==allowed_ids:
        temporary=None
        try:
            artifact.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            with tempfile.NamedTemporaryFile(dir=artifact.parent,suffix='.tmp',delete=False) as file:
                temporary=file.name
                np.savez(file,ids=np.array(ids),matrix=matrix,texts=np.array(texts))
            os.replace(temporary,artifact)
            size=0
            for path in sorted(artifact.parent.glob('*.npz'),key=lambda p:p.stat().st_mtime,reverse=True):
                info=path.stat();size+=info.st_size
                if size>512*1024*1024 or time.time()-info.st_mtime>7*86400:path.unlink(missing_ok=True)
        except OSError:pass
        finally:
            if temporary:Path(temporary).unlink(missing_ok=True)
    return ids,matrix,texts


def ready_index(db, sheets, scope):
    if db is None or not settings.embedding_api_url:
        return None, 'disabled'
    sources=tuple(sorted(s.source_id for s in sheets))
    from app.services.import_jobs import fingerprint
    from app.db.models import KnowledgeSourceModel
    versions=db.execute(select(SourceIndexModel,KnowledgeSourceModel.updated_at).join(KnowledgeSourceModel,
        KnowledgeSourceModel.id==SourceIndexModel.source_id).where(SourceIndexModel.source_id.in_(sources))).all()
    current=len(versions)==len(set(sources)) and all(i.fingerprint==fingerprint() and i.revision==i.indexed_revision for i,_ in versions)
    generation='field-children-v2' if current else 'person-v1'+('@'+settings.embedding_revision if settings.embedding_revision else '')
    stamp=sorted((i.source_id,i.fingerprint,i.indexed_revision,str(updated)) for i,updated in versions) if current else None
    artifact=artifact_path(db,sheets,generation,stamp)
    # Without a revision scope, hash content; diagnostics cannot reuse stale profiles.
    revision=scope if scope else hashlib.sha256(repr([(s.source_id,s.rows) for s in sheets]).encode()).hexdigest()
    key=hashlib.sha256(repr((str(db.get_bind().url),sources,revision,
        settings.embedding_api_url,settings.embedding_model,str(artifact),artifact.exists())).encode()).digest()
    cached=_cache.get(key)
    if cached is not None:
        return cached, 'ready' if cached[0] else 'empty'
    with _lock:
        job=_pending.get(key)
        if job:
            future,started=job
            if not future.done():
                return None, 'warming'
            try:
                cached=future.result()
            except Exception:
                if monotonic()-started < 30:
                    return None, 'unavailable'
                del _pending[key]
                return None, 'unavailable'
            del _pending[key]
            _cache.put(key,cached)
            return cached, 'ready' if cached[0] else 'empty'
        # Bound running + queued index loads even with many users/bases.
        if len(_pending)>=8:
            for old,(future,_) in list(_pending.items()):
                if future.done():
                    try:_cache.put(old,future.result())
                    except Exception:pass
                    del _pending[old]
            if len(_pending)>=8:
                return None, 'busy'
        allowed={r.get('talent_id') for s in sheets for r in s.rows if r.get('talent_id')}
        future=_pool.submit(_load,db.get_bind(),sources,settings.embedding_model,artifact,allowed)
        _pending[key]=(future,monotonic())
    try:cached=future.result(timeout=.3)
    except FutureTimeout:return None,'warming'
    except Exception:return None,'unavailable'
    with _lock:_pending.pop(key,None)
    _cache.put(key,cached)
    return cached,'ready' if cached[0] else 'empty'


def person_scores(index, vector, allowed, *, include_passages=False):
    ids,matrix=index[:2]
    query=np.asarray(vector,dtype=np.float32)
    if matrix.ndim!=2 or query.ndim!=1 or matrix.shape[1]!=len(query) or not np.isfinite(query).all():
        raise ValueError('Query/index dimensions differ')
    norm=np.linalg.norm(query)
    if norm<=0:
        raise ValueError('Empty query vector')
    scores=matrix@(query/norm)
    result={}
    passages={}
    for i,(person,score) in enumerate(zip(ids,scores)):
        if person in allowed and score>0:
            result[person]=max(float(score),result.get(person,-1))
            if include_passages and len(index)>2:
                passages.setdefault(person,[]).append((float(score),index[2][i]))
    if include_passages:return result,{p:[text for _,text in sorted(items,reverse=True)[:2]] for p,items in passages.items()}
    return result
