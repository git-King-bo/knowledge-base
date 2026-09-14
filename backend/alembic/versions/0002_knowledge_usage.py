"""Knowledge ingestion and token usage tables; preserve existing local data.

Revision ID: 0002_knowledge_usage
Revises: 0001_initial
"""
from alembic import op
from app.db.models import (AIActivityLogModel, KnowledgeBaseModel, KnowledgeBaseSourceModel,
                           KnowledgeSourceModel, KnowledgeChunkModel,
                           KnowledgeChunkEmbeddingModel, TokenUsageModel)

revision = '0002_knowledge_usage'
down_revision = '0001_initial'
branch_labels = None
depends_on = None

TABLES = [AIActivityLogModel.__table__, KnowledgeBaseModel.__table__,
          KnowledgeSourceModel.__table__, KnowledgeBaseSourceModel.__table__,
          KnowledgeChunkModel.__table__, KnowledgeChunkEmbeddingModel.__table__,
          TokenUsageModel.__table__]


def upgrade():
    for table in TABLES:
        table.create(bind=op.get_bind(), checkfirst=True)


def downgrade():
    for table in reversed(TABLES):
        table.drop(bind=op.get_bind(), checkfirst=True)
