import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import Column, MetaData, String, Table, Text, create_engine, event
from scripts.replace_mysql_from_sqlite import digest


class MigrationDigestTests(unittest.TestCase):
    def test_digest_overrides_buffered_connection_and_restores_options(self):
        engine = create_engine('sqlite://')
        table = Table('records', MetaData(), Column('id', String, primary_key=True), Column('body', Text))
        table.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(table.insert(), [{'id': 'b', 'body': 'second'}, {'id': 'a', 'body': 'first'}])
        observed = []
        def observe(conn, cursor, statement, parameters, context, many):
            if statement.startswith('SELECT'):
                observed.append(context.execution_options.get('stream_results'))
        event.listen(engine, 'before_cursor_execute', observe)
        with engine.connect().execution_options(stream_results=False) as connection:
            first = digest(connection, table)
            self.assertEqual(first[0], 2)
            self.assertFalse(connection.get_execution_options()['stream_results'])
            self.assertEqual(first, digest(connection, table))
            connection.execute(table.update().where(table.c.id == 'a').values(body='changed'))
            self.assertNotEqual(first, digest(connection, table))
        self.assertEqual(observed, [True, True, True])
        engine.dispose()


if __name__ == '__main__':
    unittest.main()
