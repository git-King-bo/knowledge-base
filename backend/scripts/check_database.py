"""只检查连接和表结构，不建表、不启动任务，也不输出密码。"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import inspect, text
from app.db.session import engine, Base
from app.db import models  # 注册模型，用于只读检查同名表。


def main():
    print('Selected database:', engine.dialect.name)
    with engine.connect() as connection:
        print('Connection check:', connection.scalar(text('SELECT 1')))
        inspector = inspect(connection)
        existing = set(inspector.get_table_names())
        expected = set(Base.metadata.tables)
        print('Existing table count:', len(existing))
        print('Application tables present:', ', '.join(sorted(existing & expected)) or '(none)')
        if engine.dialect.name == 'mysql':
            print('MySQL version:', connection.scalar(text('SELECT VERSION()')))
        if 'alembic_version' in existing:
            print('Migration revision:', connection.scalar(text('SELECT version_num FROM alembic_version')))
    engine.dispose()


if __name__ == '__main__':
    main()
