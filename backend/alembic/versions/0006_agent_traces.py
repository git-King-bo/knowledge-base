"""Per-conversation agent execution traces."""
from alembic import op
from app.db.models import AgentTraceModel
revision = '0006_agent_traces'
down_revision = '0005_provider_thinking'
branch_labels = depends_on = None

def upgrade():
    AgentTraceModel.__table__.create(op.get_bind(), checkfirst=True)
    from app.db.trace_schema import upgrade_trace_counters
    upgrade_trace_counters(op.get_bind())

def downgrade():
    AgentTraceModel.__table__.drop(op.get_bind(), checkfirst=True)
