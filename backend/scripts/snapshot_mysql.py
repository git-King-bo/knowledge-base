"""将 MySQL 一致性快照保存为新的 SQLite 文件，供备份或首次部署回退使用。

只读取 MySQL，不覆盖已有目标，不复制登录会话。上传文件和加密密钥需独立保管。
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import create_engine, select, text
from app.db.session import engine, Base
from app.db import models


def export_snapshot(output):
    if engine.dialect.name != 'mysql':
        raise RuntimeError('MySQL must be selected for this export')
    output.parent.mkdir(parents=True, exist_ok=True)
    # 排他创建，失败留下文件以便排查，不覆盖任何现有回退库。
    output.touch(mode=0o600, exist_ok=False)
    destination = create_engine('sqlite:///' + str(output.resolve()))
    Base.metadata.create_all(destination)
    counts = {}
    with engine.connect() as source, destination.begin() as target:
        source.exec_driver_sql('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        source.exec_driver_sql('START TRANSACTION WITH CONSISTENT SNAPSHOT')
        for table in Base.metadata.sorted_tables:
            count = 0
            if table.name != 'login_sessions':
                for batch in source.execute(select(table)).mappings().partitions(100):
                    target.execute(table.insert(), [dict(row) for row in batch])
                    count += len(batch)
            counts[table.name] = count
        revision = source.scalar(text('SELECT version_num FROM alembic_version'))
        target.execute(text('CREATE TABLE alembic_version(version_num VARCHAR(32) PRIMARY KEY)'))
        target.execute(text('INSERT INTO alembic_version VALUES (:revision)'), {'revision': revision})
        if target.exec_driver_sql('PRAGMA foreign_key_check').first():
            raise RuntimeError('Snapshot contains invalid foreign keys')
        if target.exec_driver_sql('PRAGMA integrity_check').scalar() != 'ok':
            raise RuntimeError('Snapshot integrity check failed')
        source.rollback()
    destination.dispose()
    print('Snapshot verified:', output, counts)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    export_snapshot(parser.parse_args().output)
