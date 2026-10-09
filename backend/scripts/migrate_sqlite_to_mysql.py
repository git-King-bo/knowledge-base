"""将 SQLite 快照合并到现有 MySQL；保留目标记录，冲突时停止，不覆盖业务数据。

先停止本项目所有写入进程。默认只预检，传 --apply 才备份并在单个事务内写入。
同名账号映射到目标账号（保留目标密码）；旧登录会话不导入。
同 ID 的模型配置沿用目标设置；同用户同日期的用量累加，避免预算被重置。
迁移报告包含源文件 SHA256 和各表数量，不包含密码或业务正文。
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import create_engine, select, func, inspect, text, and_
from app.db.session import engine, Base
from app.db import models
from scripts.prepare_mysql import snapshot


def merge(source, target, apply=False):
    user_table = Base.metadata.tables['users']
    target_users = {r['username']: r['id'] for r in target.execute(select(user_table)).mappings()}
    users = list(source.execute(select(user_table)).mappings())
    user_map = {r['id']: target_users.get(r['username'], r['id']) for r in users}
    report = {}
    for table in Base.metadata.sorted_tables:
        rows = [dict(r) for r in source.execute(select(table)).mappings()]
        existing = {tuple(r[c.name] for c in table.primary_key): dict(r)
                    for r in target.execute(select(table)).mappings()}
        added = skipped = combined = 0
        pending = []
        for row in rows:
            if table.name == 'login_sessions':
                skipped += 1
                continue
            if 'user_id' in row:
                row['user_id'] = user_map.get(row['user_id'], row['user_id'])
            if table.name == 'users':
                row['id'] = user_map[row['id']]
            key = tuple(row[c.name] for c in table.primary_key)
            old = existing.get(key)
            if old is not None:
                if table.name == 'request_budgets':
                    if apply:
                        condition = and_(*(c == row[c.name] for c in table.primary_key))
                        target.execute(table.update().where(condition).values(
                            **{field: old[field] + row[field] for field in ('requests', 'tokens', 'reserved')}))
                    combined += 1
                elif table.name in ('users', 'ai_providers', 'ai_models') or old == row:
                    skipped += 1
                else:
                    raise RuntimeError(f'Conflicting existing record in {table.name}; migration rolled back')
            else:
                if table.name == 'ai_providers':
                    # 目标默认模型已由用户配置，迁入的其它服务不抢占默认。
                    row['is_default'] = False
                pending.append(row)
                added += 1
        if apply:
            # 每批控制体积，长文本和向量不会合并成超大 SQL 包。
            for offset in range(0, len(pending), 50):
                target.execute(table.insert(), pending[offset:offset + 50])
        report[table.name] = {'source': len(rows), 'before': len(existing),
                              'inserted': added, 'preserved': skipped, 'combined': combined,
                              'after_expected': len(existing) + added}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if engine.dialect.name != 'mysql':
        raise RuntimeError('MySQL must be selected; run with APP_DATABASE_MODE=mysql')
    digest = hashlib.sha256(args.source.read_bytes()).hexdigest()
    marker = 'sqlite-import-' + digest
    manifest = args.source.with_suffix('.migration.json')
    if args.apply and manifest.exists():
        raise RuntimeError('This snapshot already has a migration report; refusing to double-count budgets')
    source_engine = create_engine('sqlite://', creator=lambda: sqlite3.connect(
        args.source.resolve().as_uri() + '?mode=ro', uri=True))
    with source_engine.connect() as source, engine.connect() as target:
        audit = Base.metadata.tables['audit_events']
        if target.scalar(select(audit.c.id).where(audit.c.id == marker)):
            raise RuntimeError('This snapshot is already recorded as migrated in MySQL')
        # 先确认所有表可读且没有冲突，然后备份本项目目标表。
        preview = merge(source, target)
        print(json.dumps(preview, ensure_ascii=False))
        if not args.apply:
            return
        target.rollback()
        target.exec_driver_sql('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        target.exec_driver_sql('START TRANSACTION WITH CONSISTENT SNAPSHOT')
        tables = sorted(set(inspect(target).get_table_names()) & set(Base.metadata.tables))
        backup = snapshot(target, tables + ['alembic_version'])
        target.rollback()
        with target.begin():
            report = merge(source, target, apply=True)
            for name, counts in report.items():
                actual = target.scalar(select(func.count()).select_from(Base.metadata.tables[name]))
                if actual != counts['after_expected']:
                    raise RuntimeError(f'Post-migration count mismatch: {name}')
            # 同一事务内登记，避免提交成功但本地报告写入失败后重复累加用量。
            target.execute(audit.insert().values(id=marker, user_id=None, action='sqlite.imported',
                target=digest, detail='SQLite snapshot merged; source retained',
                created_at=datetime.now(timezone.utc).replace(tzinfo=None)))
            report['audit_events']['after_expected'] += 1
        manifest.write_text(json.dumps({'source_sha256':digest, 'backup':str(backup),
            'completed_at':datetime.now(timezone.utc).isoformat(), 'tables':report}, indent=2))
        manifest.chmod(0o600)
        print('Migration committed. Report:', manifest)
        print('Pre-migration MySQL backup:', backup)
    source_engine.dispose()


if __name__ == '__main__':
    main()
