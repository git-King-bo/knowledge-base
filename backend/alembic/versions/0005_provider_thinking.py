"""Persist an explicit thinking-mode choice without changing existing model defaults."""
from alembic import op
import sqlalchemy as sa
revision = '0005_provider_thinking'
down_revision = '0004_production'
branch_labels = None
depends_on = None

def upgrade():
    if 'enable_thinking' not in {c['name'] for c in sa.inspect(op.get_bind()).get_columns('ai_providers')}:
        op.add_column('ai_providers', sa.Column('enable_thinking', sa.Boolean(), nullable=True))

def downgrade():
    op.drop_column('ai_providers', 'enable_thinking')
