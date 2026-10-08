"""接管已有同结构 MySQL 表：先备份，再补表、扩容文本列和登记迁移版本。

在 backend 目录运行：APP_DATABASE_MODE=mysql .venv/bin/python scripts/prepare_mysql.py
备份仅包含本项目已有表，可在独立空库中解压后用 mysql 客户端恢复。
不导入本地 SQLite、不删除原有表或数据、不修改无关业务表。
操作期间请停止其他写入此知识库的应用；MySQL DDL 无法整体回滚。
"""
from datetime import datetime, timezone
import gzip
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from app.db.session import engine, Base
from app.db import models
from app.db.mysql_schema import widen_mysql_text


def snapshot(connection, tables):
    root = Path('storage/backups')
    root.mkdir(parents=True, exist_ok=True)
    path = root / datetime.now(timezone.utc).strftime('before-mysql-%Y%m%dT%H%M%S%f.sql.gz')
    quote = connection.dialect.identifier_preparer.quote
    driver = connection.connection.driver_connection
    # 文件以 0600 创建；备份可能包含账号哈希及业务资料。
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as raw:
        with gzip.open(raw, 'wt', encoding='utf-8') as output:
            output.write('SET NAMES utf8mb4;\nSET FOREIGN_KEY_CHECKS=0;\n')
            for name in tables:
                table = quote(name)
                ddl = connection.exec_driver_sql(f'SHOW CREATE TABLE {table}').first()[1]
                output.write(ddl + ';\n')
                result = connection.exec_driver_sql(f'SELECT * FROM {table}')
                columns = ', '.join(quote(key) for key in result.keys())
                for row in result:
                    values = ', '.join(driver.escape(value) for value in row)
                    output.write(f'INSERT INTO {table} ({columns}) VALUES ({values});\n')
            output.write('SET FOREIGN_KEY_CHECKS=1;\n')
    return path


def main():
    if engine.dialect.name != 'mysql':
        raise RuntimeError('MySQL was not selected. No schema changes performed.')
    with engine.connect() as connection:
        inspector = inspect(connection)
        existing = set(inspector.get_table_names())
        application_tables = sorted(existing & set(Base.metadata.tables))
        for name in application_tables:
            expected = Base.metadata.tables[name]
            actual = {c['name'] for c in inspector.get_columns(name)}
            if set(expected.columns.keys()) != actual:
                raise RuntimeError(f'Existing table has incompatible columns: {name}; no changes performed')
            primary = set(inspector.get_pk_constraint(name)['constrained_columns'])
            if primary != set(expected.primary_key.columns.keys()):
                raise RuntimeError(f'Existing table has incompatible primary key: {name}')
        connection.rollback()
        connection.exec_driver_sql('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        connection.exec_driver_sql('START TRANSACTION WITH CONSISTENT SNAPSHOT')
        tables = application_tables + (['alembic_version'] if 'alembic_version' in existing else [])
        print('Backup:', snapshot(connection, tables))
        connection.rollback()

    # 保留已有表字段与字符集，创建缺失表时匹配外键引用列的排序规则。
    with engine.begin() as connection:
        inspector = inspect(connection)
        collations = set()
        for name in application_tables:
            for column in inspector.get_columns(name):
                if column['name'] == 'id' and getattr(column['type'], 'collation', None):
                    collations.add(column['type'].collation)
        if len(collations) > 1:
            raise RuntimeError('Existing ID collations differ; reconcile schema before adding foreign keys')
        if collations:
            collation = collations.pop()
            for table in Base.metadata.tables.values():
                table.dialect_options['mysql']['charset'] = collation.split('_')[0]
                table.dialect_options['mysql']['collate'] = collation
        Base.metadata.create_all(connection)
        widen_mysql_text(connection)
        config = Config('alembic.ini')
        config.attributes['connection'] = connection
        if 'alembic_version' in existing:
            command.upgrade(config, 'head')
        else:
            command.stamp(config, 'head')
    print('MySQL schema ready. Existing data retained; SQLite data was not imported.')


if __name__ == '__main__':
    main()
