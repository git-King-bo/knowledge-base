"""Scheduled backup and log retention. No original knowledge/talent records are deleted."""
from datetime import timedelta
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import delete,select
from app.core.config import settings
from app.core.security import now
from app.db.session import SessionLocal,engine
from app.db.models import AIActivityLogModel,TokenUsageModel,LoginSessionModel,AuditModel
from backup_workspace import backup

if __name__=='__main__':
    if engine.dialect.name != 'sqlite':
        raise RuntimeError('SQLite maintenance cannot back up MySQL. Configure MySQL backups separately.')
    database=Path(engine.url.database).resolve(strict=True)
    path=database.parent/'storage/backups'/now().strftime('scheduled-%Y%m%dT%H%M%S.tar.gz')
    backup(database,path)
    with SessionLocal() as db:
        cutoff=now()-timedelta(days=settings.log_retention_days)
        # Keep aggregate usage while removing old raw prompts/responses from logs.
        from sqlalchemy import update
        db.execute(update(AIActivityLogModel).where(AIActivityLogModel.created_at<cutoff).values(request_text='',response_text=''))
        db.execute(delete(LoginSessionModel).where(LoginSessionModel.expires_at<now()))
        db.commit()
    print('backup:',path,'older prompt/answer bodies scrubbed')
