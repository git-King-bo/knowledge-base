"""Team access, durable imports, talent provenance and conversations."""
from alembic import op
from app.db.models import (UserModel, LoginSessionModel, BaseAccessModel, AuditModel,
    RequestBudgetModel, SourceIndexModel, ImportJobModel, TalentRevisionModel,
    ChunkTalentModel, SavedConversationModel, TrashModel)
revision = '0004_production'
down_revision = '0003_talents'
branch_labels = depends_on = None
TABLES = [UserModel, LoginSessionModel, BaseAccessModel, AuditModel, RequestBudgetModel,
          SourceIndexModel, ImportJobModel, TalentRevisionModel, ChunkTalentModel,
          SavedConversationModel, TrashModel]
def upgrade():
    for model in TABLES:
        model.__table__.create(op.get_bind(), checkfirst=True)
def downgrade():
    for model in reversed(TABLES):
        model.__table__.drop(op.get_bind(), checkfirst=True)
