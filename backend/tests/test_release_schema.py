import unittest
from unittest.mock import patch
from sqlalchemy import create_engine, text
from app.core.config import settings
from app.db.init_db import init_db

class ReleaseSchemaTests(unittest.TestCase):
    def test_matching_schema_checks_without_migrating(self):
        self.check_schema('0007_mysql_text', succeeds=True)

    def test_different_schema_blocks_without_migrating(self):
        self.check_schema('0006_agent_traces', succeeds=False)

    def check_schema(self, revision, succeeds):
        engine = create_engine('sqlite://')
        self.addCleanup(engine.dispose)
        with engine.begin() as connection:
            connection.execute(text('CREATE TABLE alembic_version(version_num VARCHAR(32))'))
            connection.execute(text('INSERT INTO alembic_version VALUES (:value)'), {'value':revision})
        with patch('app.db.init_db.engine', engine), patch.object(settings,'app_env','production'), \
             patch.object(settings,'migration_mode','check'), patch('alembic.command.upgrade') as upgrade:
            if succeeds:
                init_db()
            else:
                with self.assertRaisesRegex(RuntimeError,'schema does not match'):
                    init_db()
            upgrade.assert_not_called()
        with engine.connect() as connection:
            self.assertEqual(connection.scalar(text('SELECT version_num FROM alembic_version')),revision)
