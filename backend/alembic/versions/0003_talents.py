"""Add structured talent records without changing knowledge chunks or vectors."""
from alembic import op
from app.db.models import TalentModel

revision = '0003_talents'
down_revision = '0002_knowledge_usage'
branch_labels = None
depends_on = None


def upgrade():
    TalentModel.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade():
    TalentModel.__table__.drop(bind=op.get_bind(), checkfirst=True)
