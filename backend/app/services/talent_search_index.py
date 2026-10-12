"""Bounded asynchronous vector loading. Request threads never fetch vector bodies.

Only source IDs authorized by the request are loaded. Each worker owns its DB
session; caches include database, source revisions, provider and model identity.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from time import monotonic
import hashlib
import json
import numpy as np
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db.models import KnowledgeChunkModel as Chunk, KnowledgeChunkEmbeddingModel as Embedding, ChunkTalentModel, SourceIndexModel
from app.services.query_cache import BoundedCache

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='talent-index')
_cache = BoundedCache(max_bytes=128*1024*1024, max_entries=8, ttl=120)
_pending = {}
_lock = Lock()


def artifact_path(db, sheets):
    # Content identity includes ownership and every business field. Updated source
    # text, model, endpoint or database select a different immutable artifact.
    identity=(str(db.get_bind().url),settings.embedding_api_url,settings.embedding_model,'person-v1',
        [(s.source_id,s.sheet,s.rows) for s in sheets])
    digest=hashlib.sha256(json.dumps(identity,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()
    return Path(settings.upload_dir).parent/'search-index'/f'{digest}.npz'


def profile_document(fields):
    priority=['姓名','当前机构','当前职务','所在国家／城市','领域','细分关键词','研究方向',
        '详细个人简介','代表成果','创业／项目经历','工作经历','教育经历','技术角色定位']
    # Keep a bounded contribution from each field; complete originals remain in
    # the BM25 index and citations. Never embed contact details or operating notes.
    return '\n'.join(f'{f}：{str(fields[f])[:450]}' for f in priority if fields.get(f))[:6000]


def _load(engine, source_ids, model, artifact=None, allowed_ids=None):
    if artifact and artifact.is_file():
        try:
            with np.load(artifact,allow_pickle=False) as data:
                ids=data['ids'].tolist();matrix=data['matrix'].astype(np.float32)
            if (matrix.ndim==2 and matrix.shape[0]==len(ids) and len(ids)==len(set(ids))
                    and set(ids)==allowed_ids and np.isfinite(matrix).all()):
                matrix/=np.maximum(np.linalg.norm(matrix,axis=1,keepdims=True),1e-12)
                return ids,matrix
        except (OSError, ValueError, KeyError):
            pass  # An incomplete/corrupt local artifact must not disable DB fallback.
    with Session(engine) as db:
        stale = select(SourceIndexModel.source_id).where(SourceIndexModel.edited.is_(True), SourceIndexModel.revision != SourceIndexModel.indexed_revision)
        rows = db.execute(select(ChunkTalentModel.talent_id, Embedding.embedding_json)
            .join(Chunk, Chunk.id == ChunkTalentModel.chunk_id)
            .join(Embedding, Embedding.chunk_id == Chunk.id)
            .where(Chunk.source_id.in_(source_ids), ~Chunk.source_id.in_(stale), Embedding.embedding_model == model)).all()
    ids=[]; vectors=[]; dimension=None
    for person, raw in rows:
        vector=np.asarray(json.loads(raw), dtype=np.float32)
        if vector.ndim != 1 or not len(vector) or not np.isfinite(vector).all():
            continue
        if dimension is None:
            dimension=len(vector)
        if len(vector) != dimension:
            continue
        ids.append(person); vectors.append(vector)
    if not vectors:
        return ids, np.empty((0, 0),dtype=np.float32)
    matrix=np.stack(vectors)
    matrix/=np.maximum(np.linalg.norm(matrix,axis=1,keepdims=True),1e-12)
    return ids,matrix


def ready_index(db, sheets, scope):
    if db is None or not settings.embedding_api_url:
        return None, 'disabled'
    sources=tuple(sorted(s.source_id for s in sheets))
    artifact=artifact_path(db,sheets)
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
        _pending[key]=(_pool.submit(_load,db.get_bind(),sources,settings.embedding_model,artifact,allowed),monotonic())
    return None, 'warming'


def person_scores(index, vector, allowed):
    ids,matrix=index
    query=np.asarray(vector,dtype=np.float32)
    if matrix.ndim!=2 or query.ndim!=1 or matrix.shape[1]!=len(query) or not np.isfinite(query).all():
        raise ValueError('Query/index dimensions differ')
    norm=np.linalg.norm(query)
    if norm<=0:
        raise ValueError('Empty query vector')
    scores=matrix@(query/norm)
    result={}
    for person,score in zip(ids,scores):
        if person in allowed and score>0:
            result[person]=max(float(score),result.get(person,-1))
    return result
