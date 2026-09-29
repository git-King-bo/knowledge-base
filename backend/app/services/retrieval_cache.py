"""Bounded LRU of decoded matrices; versioned by DB, source timestamps and model."""
from collections import OrderedDict
import json
import threading
import numpy as np

_cache=OrderedDict()
_lock=threading.Lock()

def dense_scores(rows,query,model,database_key):
    signature=(database_key,model,len(query),tuple((r.id,e.created_at,e.embedding_dim) for r,e in rows if e and e.embedding_model==model))
    with _lock:
        cached=_cache.get(signature)
        if cached is not None:_cache.move_to_end(signature)
    if cached is None:
        ids=[];vectors=[]
        for record,embedding in rows:
            if embedding and embedding.embedding_model==model:
                vector=json.loads(embedding.embedding_json)
                if len(vector)==len(query) and all(np.isfinite(vector)):
                    ids.append(record.id);vectors.append(vector)
        matrix=np.asarray(vectors,dtype=np.float32)
        if vectors:
            norms=np.linalg.norm(matrix,axis=1,keepdims=True)
            matrix=matrix/np.maximum(norms,1e-12)
        cached=(ids,matrix)
        if matrix.nbytes<=64*1024*1024:
            with _lock:
                _cache[signature]=cached
                while len(_cache)>4:_cache.popitem(last=False)
    ids,matrix=cached
    if not ids:return {}
    query=np.asarray(query,dtype=np.float32)
    norm=np.linalg.norm(query)
    if not norm or not np.isfinite(norm):return {}
    return dict(zip(ids,(matrix@(query/norm)).tolist()))
