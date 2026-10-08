from collections.abc import Generator

from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


from app.db.connection import select_engine

engine = select_engine(settings)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

from sqlalchemy import event

@event.listens_for(Session, 'do_orm_execute')
def scope_workspace(execute_state):
    user = execute_state.session.info.get('actor')
    if not user or user[1] == 'admin' or not execute_state.is_select or execute_state.is_column_load:
        return
    from sqlalchemy import select
    from sqlalchemy.orm import with_loader_criteria
    from app.db.models import (BaseAccessModel, KnowledgeBaseModel, KnowledgeBaseSourceModel,
                               KnowledgeSourceModel, KnowledgeChunkModel, TalentModel)
    uid = user[0]
    bases = select(BaseAccessModel.base_id).where(BaseAccessModel.user_id == uid)
    sources = select(KnowledgeBaseSourceModel.source_id).where(KnowledgeBaseSourceModel.knowledge_base_id.in_(bases))
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(KnowledgeBaseModel, KnowledgeBaseModel.id.in_(bases), include_aliases=True),
        with_loader_criteria(KnowledgeSourceModel, KnowledgeSourceModel.id.in_(sources), include_aliases=True),
        with_loader_criteria(KnowledgeChunkModel, KnowledgeChunkModel.source_id.in_(sources), include_aliases=True),
        with_loader_criteria(TalentModel, TalentModel.source_id.in_(sources), include_aliases=True))
