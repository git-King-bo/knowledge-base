"""Bounded LRU of decoded matrices; versioned by DB, source timestamps and model."""
from collections import OrderedDict
import json
import threading
import hashlib
import os
from pathlib import Path
import tempfile
import time
from zipfile import BadZipFile
import numpy as np

_cache=OrderedDict()
_lock=threading.Lock()

def _disk_path(directory, signature):
    # Never store database credentials in a filename or serialized metadata.
    digest = hashlib.sha256(repr(signature).encode()).hexdigest()
    return Path(directory) / (digest + '.npz')

def _read_matrix(path, dimensions, allowed_ids):
    try:
        with np.load(path, allow_pickle=False) as data:
            ids = data['ids'].tolist()
            matrix = data['matrix']
        if (matrix.shape != (len(ids), dimensions) or len(set(ids)) != len(ids)
                or not set(ids).issubset(allowed_ids) or not np.isfinite(matrix).all()):
            return None
        os.utime(path, None)
        return ids, matrix
    except (OSError, ValueError, KeyError, EOFError, BadZipFile):
        return None

def _write_matrix(path, cached):
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix='.tmp', delete=False) as file:
            temporary = file.name
            np.savez(file, ids=np.asarray(cached[0], dtype=str), matrix=cached[1])
        os.replace(temporary, path)
        # Bound runtime disk use and discard old index versions. Failures are harmless.
        files = sorted(path.parent.glob('*.npz'), key=lambda p: p.stat().st_mtime, reverse=True)
        size = 0
        for item in files:
            stat = item.stat()
            size += stat.st_size
            if size > 256*1024*1024 or time.time()-stat.st_mtime > 7*86400:
                item.unlink(missing_ok=True)
    except OSError:
        pass
    finally:
        if temporary:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError:
                pass

def dense_scores(rows,query,model,database_key,*,load_vectors=None,cache_dir=None):
    signature=(database_key,model,len(query),tuple((r.id,e.created_at,e.embedding_dim) for r,e in rows if e and e.embedding_model==model))
    with _lock:
        cached=_cache.get(signature)
        if cached is not None:_cache.move_to_end(signature)
    from app.services.agent_trace import trace_note
    trace_note('向量矩阵缓存', hit=cached is not None, model=model, dimensions=len(query), reason='缓存索引矩阵，不缓存本次模型回答')
    path = _disk_path(cache_dir, signature) if cache_dir else None
    if cached is None and path is not None:
        cached = _read_matrix(path, len(query), {r.id for r,e in rows if e and e.embedding_model==model})
        trace_note('向量矩阵磁盘缓存', hit=cached is not None)
    if cached is None:
        # Read large vector bodies only after checking lightweight index metadata.
        loaded = load_vectors() if load_vectors is not None else None
        ids=[];vectors=[]
        for record,embedding in rows:
            if embedding and embedding.embedding_model==model:
                raw = loaded.get(record.id) if loaded is not None else embedding.embedding_json
                if raw is None:
                    continue
                vector=json.loads(raw)
                if len(vector)==len(query) and all(np.isfinite(vector)):
                    ids.append(record.id);vectors.append(vector)
        matrix=np.asarray(vectors,dtype=np.float32)
        if vectors:
            norms=np.linalg.norm(matrix,axis=1,keepdims=True)
            matrix=matrix/np.maximum(norms,1e-12)
        cached=(ids,matrix)
        if path is not None and ids and matrix.nbytes<=64*1024*1024:
            _write_matrix(path,cached)
    if cached[1].nbytes<=64*1024*1024:
        with _lock:
            _cache[signature]=cached
            _cache.move_to_end(signature)
            while len(_cache)>4:_cache.popitem(last=False)
    ids,matrix=cached
    if not ids:return {}
    query=np.asarray(query,dtype=np.float32)
    norm=np.linalg.norm(query)
    if not norm or not np.isfinite(norm):return {}
    return dict(zip(ids,(matrix@(query/norm)).tolist()))
