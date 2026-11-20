"""Index source lookups and cover embedding metadata scans."""
from alembic import op
from app.db.retrieval_schema import upgrade_retrieval_indexes

revision='0009_retrieval_indexes'
down_revision='0008_index_generation'
branch_labels=depends_on=None


def upgrade():
    upgrade_retrieval_indexes(op.get_bind())


def downgrade():
    # Additive performance indexes remain safe for the previous application.
    pass
