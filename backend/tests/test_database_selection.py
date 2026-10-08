import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from sqlalchemy import inspect, text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import OperationalError
from sqlalchemy.schema import CreateIndex, CreateTable

from app.core.config import Settings
from app.db.connection import build_engine, select_engine
from app.db.models import Base, RequestBudgetModel
from app.core.limits import ensure_budget
from sqlalchemy.orm import Session


class DatabaseSelectionTests(unittest.TestCase):
    def config(self, **values):
        return Settings(_env_file=None, APP_DATABASE_MODE='auto',
                        XINIU_MYSQL_HOST='db.invalid', XINIU_MYSQL_USER='fixture',
                        XINIU_MYSQL_PASSWORD='secret@:/%', XINIU_MYSQL_DATABASE='fixture',
                        DATABASE_URL='sqlite://', **values)

    def test_mysql_selected_and_password_not_interpolated(self):
        candidate = MagicMock()
        with patch('app.db.connection.build_engine', return_value=candidate) as factory:
            self.assertIs(select_engine(self.config()), candidate)
        url = factory.call_args.args[0]
        self.assertEqual(url.password, 'secret@:/%')
        candidate.connect.return_value.__enter__.return_value.execute.assert_called_once()

    def test_failure_falls_back_without_leaking_credentials(self):
        candidate = MagicMock()
        candidate.connect.side_effect = OperationalError('SELECT 1', {}, Exception('secret@:/%'))
        fallback = MagicMock()
        with patch('app.db.connection.build_engine', side_effect=[candidate, fallback]), self.assertLogs('app.db.connection', logging.WARNING) as logs:
            self.assertIs(select_engine(self.config()), fallback)
        candidate.dispose.assert_called_once()
        self.assertNotIn('secret@:/%', ' '.join(logs.output))

    def test_strict_mysql_never_falls_back(self):
        settings = self.config()
        settings.database_mode = 'mysql'
        candidate = MagicMock()
        candidate.connect.side_effect = OperationalError('SELECT 1', {}, Exception('secret@:/%'))
        with patch('app.db.connection.build_engine', return_value=candidate) as factory:
            with self.assertRaisesRegex(RuntimeError, 'fallback disabled'):
                select_engine(settings)
        self.assertEqual(factory.call_count, 1)

    def test_explicit_sqlite_does_not_probe_mysql(self):
        settings = self.config()
        settings.database_mode = 'sqlite'
        with patch('app.db.connection.build_engine') as factory:
            select_engine(settings)
        self.assertEqual(factory.call_args.args[0].get_backend_name(), 'sqlite')

    def test_sqlite_persists_and_enforces_foreign_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            url = 'sqlite:///' + str(Path(folder) / 'fallback.db')
            engine = build_engine(url)
            with engine.begin() as connection:
                self.assertEqual(connection.scalar(text('PRAGMA foreign_keys')), 1)
                connection.execute(text('CREATE TABLE marker (value INTEGER)'))
                connection.execute(text('INSERT INTO marker VALUES (42)'))
            engine.dispose()
            engine = build_engine(url)
            with engine.connect() as connection:
                self.assertEqual(connection.scalar(text('SELECT value FROM marker')), 42)
            engine.dispose()

    def test_duplicate_budget_does_not_reset_usage(self):
        engine = build_engine('sqlite://')
        RequestBudgetModel.__table__.create(engine)
        with Session(engine) as db:
            ensure_budget(db, 'u', '2026-10-08')
            row = db.get(RequestBudgetModel, ('u', '2026-10-08'))
            row.tokens, row.requests, row.reserved = 80, 3, 12
            db.flush()
            ensure_budget(db, 'u', '2026-10-08')
            db.expire_all()
            self.assertEqual((row.tokens, row.requests, row.reserved), (80, 3, 12))
        engine.dispose()

    def test_all_mysql_tables_and_indexes_compile(self):
        dialect = mysql.dialect()
        for table in Base.metadata.sorted_tables:
            str(CreateTable(table).compile(dialect=dialect))
            for index in table.indexes:
                ddl = str(CreateIndex(index).compile(dialect=dialect))
                if index.name == 'ix_talents_name':
                    self.assertIn('(191)', ddl)
        self.assertIn('LONGTEXT', str(CreateTable(Base.metadata.tables['knowledge_sources']).compile(dialect=dialect)))
