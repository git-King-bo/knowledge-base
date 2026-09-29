"""Add trace counters to databases created during an earlier development reload."""
import json
from sqlalchemy import inspect, text


def upgrade_trace_counters(connection):
    inspector = inspect(connection)
    if not inspector.has_table('agent_traces'):
        return
    existing = {column['name'] for column in inspector.get_columns('agent_traces')}
    definitions = {
        'call_count': 'INTEGER NOT NULL DEFAULT 0',
        'unknown_calls': 'INTEGER NOT NULL DEFAULT 0',
        'total_tokens': 'INTEGER NOT NULL DEFAULT 0',
        'input_tokens': 'INTEGER',
        'output_tokens': 'INTEGER',
        'cached_tokens': 'INTEGER',
    }
    missing = [name for name in definitions if name not in existing]
    if not missing:
        return
    for name in missing:
        connection.execute(text(f'ALTER TABLE agent_traces ADD COLUMN {name} {definitions[name]}'))
    # Recover aggregates from persisted provider usage, preserving unknown values.
    rows = connection.execute(text('SELECT id, calls_json FROM agent_traces')).mappings().all()
    for row in rows:
        calls = json.loads(row['calls_json'] or '[]')
        values = {
            'id': row['id'], 'call_count': len(calls),
            'unknown_calls': sum(call.get('total_tokens') is None for call in calls),
            'total_tokens': sum(call.get('total_tokens') or 0 for call in calls),
        }
        for key in ('input_tokens', 'output_tokens', 'cached_tokens'):
            counts = [call.get(key) for call in calls]
            values[key] = None if any(value is None for value in counts) else sum(counts)
        assignments = ', '.join(f'{name} = :{name}' for name in missing)
        connection.execute(text(f'UPDATE agent_traces SET {assignments} WHERE id = :id'), values)
