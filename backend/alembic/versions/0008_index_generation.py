"""Persist index generation on jobs; old binaries tolerate the additive column."""
from alembic import op
from app.db.index_schema import upgrade_index_jobs

revision='0008_index_generation'
down_revision='0007_mysql_text'
branch_labels=depends_on=None


def upgrade():
    upgrade_index_jobs(op.get_bind())


def downgrade():
    # Preserve retry metadata and allow the previous binary to ignore the column.
    pass
