import json
import unittest
from sqlalchemy import create_engine, inspect, text
from app.db.trace_schema import upgrade_trace_counters


class TraceSchemaTests(unittest.TestCase):
    def test_partial_development_table_is_upgraded_without_losing_history(self):
        engine = create_engine('sqlite://')
        with engine.begin() as connection:
            connection.execute(text('CREATE TABLE agent_traces (id TEXT PRIMARY KEY, calls_json TEXT, answer TEXT)'))
            calls = [{'total_tokens': 125, 'input_tokens': 100, 'output_tokens': 25, 'cached_tokens': 40},
                     {'total_tokens': None, 'input_tokens': None, 'output_tokens': None, 'cached_tokens': None}]
            connection.execute(text('INSERT INTO agent_traces VALUES (:id, :calls, :answer)'),
                               {'id': 'old', 'calls': json.dumps(calls), 'answer': '原始回答'})
            connection.execute(text("INSERT INTO agent_traces VALUES ('empty', '[]', '')"))
            upgrade_trace_counters(connection)
            first = dict(connection.execute(text("SELECT * FROM agent_traces WHERE id='old'")).mappings().one())
            self.assertEqual(first['answer'], '原始回答')
            self.assertEqual(first['calls_json'], json.dumps(calls))
            self.assertEqual(first['call_count'], 2)
            self.assertEqual(first['unknown_calls'], 1)
            self.assertEqual(first['total_tokens'], 125)
            self.assertIsNone(first['input_tokens'])
            empty = connection.execute(text("SELECT * FROM agent_traces WHERE id='empty'")).mappings().one()
            self.assertEqual(empty['call_count'], 0)
            self.assertEqual(empty['input_tokens'], 0)
            upgrade_trace_counters(connection)
            self.assertEqual(first, dict(connection.execute(text("SELECT * FROM agent_traces WHERE id='old'")).mappings().one()))
        engine.dispose()
