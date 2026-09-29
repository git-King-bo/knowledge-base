"""Back up first, add new tables, encrypt secrets and fingerprint verifiably compatible sources.
Does not rebuild vectors or call any paid service. Run from backend.
"""
import hashlib
from pathlib import Path
import sys
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from app.db.session import engine,SessionLocal
from app.db.init_db import init_db
from app.db.models import KnowledgeSourceModel,KnowledgeChunkModel,KnowledgeChunkEmbeddingModel,SourceIndexModel,TalentModel
from app.core.security import initialize_security
from app.core.config import settings
from app.services.ingestion import split_into_chunks
from app.services.import_jobs import fingerprint
from app.services.talent_import import read_personnel
from backup_workspace import backup

def main():
    database=Path(engine.url.database).resolve(strict=True)
    path=database.parent/'storage/backups'/datetime.now(timezone.utc).strftime('before-production-%Y%m%dT%H%M%S.tar.gz')
    print('backup:',backup(database,path))
    from app.db.session import Base
    Base.metadata.create_all(engine)
    from sqlalchemy import inspect
    inspector = inspect(engine)
    for table in Base.metadata.sorted_tables:
        actual = {c['name'] for c in inspector.get_columns(table.name)}
        if not set(table.columns.keys()).issubset(actual):
            raise RuntimeError(f'Schema mismatch: {table.name}; do not stamp an incompatible database')
    from alembic import command
    from alembic.config import Config
    command.stamp(Config('alembic.ini'), 'head')
    compatible=0;skipped=0
    with SessionLocal() as db:
        initialize_security(db)
        for source in db.scalars(select(KnowledgeSourceModel).where(KnowledgeSourceModel.status=='parsed')):
            if db.get(SourceIndexModel,source.id):continue
            file=Path(source.storage_path)
            if not file.exists():skipped+=1;continue
            chunks=list(db.scalars(select(KnowledgeChunkModel).where(KnowledgeChunkModel.source_id==source.id).order_by(KnowledgeChunkModel.chunk_index)))
            expected=split_into_chunks(source.content_text,max_chars=settings.knowledge_chunk_max_chars,overlap=settings.knowledge_chunk_overlap_chars)
            if [x.content for x in chunks]!=[x.content for x in expected]:skipped+=1;continue
            if settings.embedding_api_url:
                embeddings=list(db.scalars(select(KnowledgeChunkEmbeddingModel).where(KnowledgeChunkEmbeddingModel.chunk_id.in_([x.id for x in chunks]))))
                if len(embeddings)!=len(chunks) or any(e.embedding_model!=settings.embedding_model for e in embeddings):skipped+=1;continue
            if source.filename.lower().endswith('.xlsx'):
                records=read_personnel(file,source.id)
                for record in records:
                    existing=db.get(TalentModel,record['id'])
                    if existing and existing.raw_data_json!=record['raw_data_json']:
                        break
                else:
                    for record in records:
                        if not db.get(TalentModel,record['id']):db.add(TalentModel(**record,created_at=datetime.now(timezone.utc)))
                    records=None
                if records is not None:skipped+=1;continue
            db.add(SourceIndexModel(source_id=source.id,sha256=hashlib.sha256(file.read_bytes()).hexdigest(),fingerprint=fingerprint(),revision=1,indexed_revision=1,edited=False))
            compatible+=1
        db.commit()
        print('compatible_sources:',compatible,'unverified_sources:',skipped)
        print('talent_records:',len(list(db.scalars(select(TalentModel.id)))))
    print('Initial administrator: admin; password is in storage/security/initial-admin-password.txt (not printed).')

if __name__=='__main__':main()
