"""Expand existing MySQL text columns for uploaded documents and conversations."""
from alembic import op
from app.db.mysql_schema import widen_mysql_text

revision = '0007_mysql_text'
down_revision = '0006_agent_traces'
branch_labels = depends_on = None


def upgrade():
    widen_mysql_text(op.get_bind())


def downgrade():
    # 不缩窄 LONGTEXT，以免截断用户资料；SQLite 无结构变化。
    pass
