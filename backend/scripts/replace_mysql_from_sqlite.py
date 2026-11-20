"""Replace this application's MySQL rows with an authoritative SQLite snapshot.

Stop all application writers first. Preview by default; --apply backs up MySQL
and replaces application rows in one transaction, checking every table's digest.
Unrelated MySQL tables are never deleted. Keep source files and encryption key.
"""
import argparse
from datetime import date, datetime
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import DateTime, String, cast, create_engine, inspect, select, text
from sqlalchemy.dialects.mysql import BINARY
from app.db.session import Base, engine
from app.db import models
from scripts.prepare_mysql import snapshot


def digest(connection, table):
    result = hashlib.sha256()
    count = 0
    ordering = [cast(c, BINARY) if connection.dialect.name == 'mysql' and isinstance(c.type, String) else c
                for c in table.primary_key.columns]
    query = select(table).order_by(*ordering)
    prior_streaming = connection.get_execution_options().get('stream_results', False)
    # Connection options override statement options in SQLAlchemy. Force the
    # connection itself to stream; buffering the vector table can exceed RAM.
    connection.execution_options(stream_results=True)
    try:
        with connection.execute(query) as rows:
            for row in rows:
                values = [v.isoformat() if isinstance(v, (date, datetime)) else
                          str(v) if isinstance(v, Decimal) else v for v in row]
                result.update(json.dumps(values, ensure_ascii=False, separators=(',', ':')).encode())
                result.update(b'\n')
                count += 1
    finally:
        connection.execution_options(stream_results=prior_streaming)
    return count, result.hexdigest()


def replace(source_path, apply=False):
    if engine.dialect.name != 'mysql':
        raise RuntimeError('APP_DATABASE_MODE=mysql required')
    source_engine = create_engine('sqlite://', creator=lambda: sqlite3.connect(
        source_path.resolve().as_uri() + '?mode=ro', uri=True))
    tables = list(Base.metadata.sorted_tables)
    with source_engine.connect() as source, engine.connect() as target:
        if source.exec_driver_sql('PRAGMA integrity_check').scalar() != 'ok':
            raise RuntimeError('Source integrity check failed')
        if source.exec_driver_sql('PRAGMA foreign_key_check').first():
            raise RuntimeError('Source foreign key check failed')
        for connection in (source, target):
            inspector = inspect(connection)
            for table in tables:
                if {c['name'] for c in inspector.get_columns(table.name)} != set(table.columns.keys()):
                    raise RuntimeError(f'Incompatible columns: {table.name}')
                if connection.dialect.name == 'mysql' and inspector.get_table_options(table.name).get('mysql_engine', '').upper() != 'INNODB':
                    raise RuntimeError(f'Transactional InnoDB table required: {table.name}')
        expected = {}
        for table in tables:
            expected[table.name] = digest(source, table)
            print('Verified source table:', table.name, expected[table.name][0], flush=True)
        with source_path.open('rb') as source_file:
            source_hash = hashlib.file_digest(source_file, 'sha256').hexdigest()
        print(json.dumps({'source_counts': {k: v[0] for k, v in expected.items()},
                          'source_sha256': source_hash}), flush=True)
        if not apply:
            return
        target.rollback()
        target.exec_driver_sql('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        target.exec_driver_sql('START TRANSACTION WITH CONSISTENT SNAPSHOT')
        target.execution_options(stream_results=True)
        backup = snapshot(target, [t.name for t in tables] + ['alembic_version'])
        target.execution_options(stream_results=False)
        with gzip.open(backup, 'rb') as compressed:
            while compressed.read(1024 * 1024):
                pass
        print('Verified MySQL backup:', backup, flush=True)
        target.rollback()
        # SQLite preserves microseconds; MySQL DATETIME defaults to second
        # precision. Preserve the source timestamps before comparing contents.
        inspector = inspect(target)
        quote = target.dialect.identifier_preparer.quote
        for table in tables:
            for column in inspector.get_columns(table.name):
                if isinstance(column['type'], DateTime) and getattr(column['type'], 'fsp', None) != 6:
                    nullable = 'NULL' if column['nullable'] else 'NOT NULL'
                    target.exec_driver_sql(f'ALTER TABLE {quote(table.name)} MODIFY COLUMN '
                                           f'{quote(column["name"])} DATETIME(6) {nullable}')
        target.commit()
        with target.begin():
            for table in reversed(tables):
                target.execute(table.delete())
            for table in tables:
                for batch in source.execute(select(table)).mappings().partitions(50):
                    target.execute(table.insert(), [dict(row) for row in batch])
                if digest(target, table) != expected[table.name]:
                    raise RuntimeError(f'Content verification failed: {table.name}')
                print('Verified destination table:', table.name, expected[table.name][0], flush=True)
            revision = source.scalar(text('SELECT version_num FROM alembic_version'))
            target.execute(text('DELETE FROM alembic_version'))
            target.execute(text('INSERT INTO alembic_version(version_num) VALUES (:v)'), {'v': revision})
        print('Committed; every application table matches the authoritative snapshot.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    replace(args.source, args.apply)
