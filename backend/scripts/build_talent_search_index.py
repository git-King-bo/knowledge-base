"""Build a complete person-level index and atomically publish a versioned artifact.

Run from backend with PYTHONPATH=. and --base-id. Existing serving vectors are
never overwritten. Successful batches are checkpointed for safe resume.
"""
import argparse
import json
import os
from pathlib import Path
import tempfile
import numpy as np
from app.db.session import SessionLocal
from app.repositories.sqlite import KnowledgeIngestionRepository
from app.services.talent_search import read_talent_sheets
from app.services.talent_search_index import artifact_path,profile_document
from app.services.embeddings import EmbeddingClient
from app.core.config import settings


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-id',required=True)
    parser.add_argument('--batch-size',type=int,default=16)
    args=parser.parse_args()
    if not 1<=args.batch_size<=32:parser.error('batch size must be 1–32')
    with SessionLocal() as db:
        repo=KnowledgeIngestionRepository(db)
        sources=repo.list_active_spreadsheet_sources(args.base_id)
        sheets,failures=read_talent_sheets(sources)
        if failures or not sheets:raise RuntimeError('Source profiles unavailable')
        path=artifact_path(db,sheets);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        if path.exists():print('Index already published:',path.name);return
        checkpoint=path.with_suffix('.jsonl')
        # Lock is specific to this immutable generation; separate generations can build independently.
        import fcntl
        with path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            vectors={}
            if checkpoint.exists():
                for line in checkpoint.read_text().splitlines():
                    try:item=json.loads(line);vectors[item['id']]=item['vector']
                    except (ValueError,KeyError):continue
            people={r['talent_id']:r['fields'] for s in sheets for r in s.rows if r.get('talent_id')}
            pending=[person for person in people if person not in vectors]
            client=EmbeddingClient(db=db,knowledge_base_id=args.base_id)
            print(json.dumps({'people':len(people),'pending':len(pending),'model':settings.embedding_model}),flush=True)
            with checkpoint.open('a') as output:
                os.chmod(checkpoint,0o600)
                for start in range(0,len(pending),args.batch_size):
                    ids=pending[start:start+args.batch_size]
                    batch=client.embed_texts([profile_document(people[i]) for i in ids])
                    for person,vector in zip(ids,batch,strict=True):
                        if not vector or not np.isfinite(vector).all():raise ValueError('Invalid embedding')
                        vectors[person]=vector;output.write(json.dumps({'id':person,'vector':vector})+'\n')
                    output.flush();os.fsync(output.fileno())
                    print(f'Completed {len(vectors)}/{len(people)}',flush=True)
            current,_=read_talent_sheets(repo.list_active_spreadsheet_sources(args.base_id))
            if artifact_path(db,current)!=path:raise RuntimeError('Source changed during build; rerun for new generation')
            ids=list(people);matrix=np.asarray([vectors[i] for i in ids],dtype=np.float32)
            matrix/=np.maximum(np.linalg.norm(matrix,axis=1,keepdims=True),1e-12)
            with tempfile.NamedTemporaryFile(dir=path.parent,suffix='.tmp',delete=False) as temp:
                np.savez(temp,ids=np.asarray(ids,dtype=str),matrix=matrix);temporary=Path(temp.name)
            os.replace(temporary,path)
            checkpoint.unlink(missing_ok=True)
            print(json.dumps({'published':path.name,'people':len(ids),'dimensions':matrix.shape[1]}),flush=True)


if __name__=='__main__':main()
