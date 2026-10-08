"""MySQL 5.7 不支持 TEXT 默认值，长资料字段需要 LONGTEXT。"""
from sqlalchemy import inspect, Text, text
from app.db.models import Base


def widen_mysql_text(connection):
    if connection.dialect.name != 'mysql':
        return
    inspector = inspect(connection)
    quote = connection.dialect.identifier_preparer.quote
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        columns = {c['name']: c for c in inspector.get_columns(table.name)}
        for column in table.columns:
            actual = columns.get(column.name)
            if not isinstance(column.type, Text) or not actual or str(actual['type']).upper().startswith('LONGTEXT'):
                continue
            # 保留现有列的可空性，只扩大容量，不截断或删除任何数据。
            nullable = 'NULL' if actual['nullable'] else 'NOT NULL'
            connection.execute(text(f'ALTER TABLE {quote(table.name)} MODIFY COLUMN '
                                    f'{quote(column.name)} LONGTEXT {nullable}'))
