"""Additive generation marker for retries across model/chunking upgrades."""
from sqlalchemy import inspect,text


def upgrade_index_jobs(connection):
    inspector=inspect(connection)
    if 'import_jobs' in inspector.get_table_names() and 'index_fingerprint' not in {
            c['name'] for c in inspector.get_columns('import_jobs')}:
        connection.execute(text("ALTER TABLE import_jobs ADD COLUMN index_fingerprint VARCHAR(64) NOT NULL DEFAULT ''"))
