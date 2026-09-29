import io
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from scripts.backup_workspace import backup,restore
from app.services.parse_worker import parse
from app.services.retrieval_cache import dense_scores
from types import SimpleNamespace

class OperationsTests(unittest.TestCase):
    def test_backup_restore_includes_files_and_checksums(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.txt';source.write_text('完整备份内容')
            database=root/'workspace.db'
            with sqlite3.connect(database) as db:
                db.execute('CREATE TABLE knowledge_sources(id TEXT PRIMARY KEY,storage_path TEXT)')
                db.execute('INSERT INTO knowledge_sources VALUES(?,?)',('source',str(source)));db.commit()
            archive=backup(database,root/'backup.tar.gz')
            target=restore(archive,root/'restored')
            with sqlite3.connect(target/'knowledge_base.db') as db:
                path=db.execute('SELECT storage_path FROM knowledge_sources').fetchone()[0]
                self.assertEqual((target/path).read_text(),'完整备份内容')
            with self.assertRaises(ValueError):restore(archive,target)
    def test_parser_rejects_zip_expansion(self):
        import zipfile
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'bad.xlsx'
            with zipfile.ZipFile(file,'w') as archive:archive.writestr('x','test')
            with patch('zipfile.ZipFile.infolist',return_value=[SimpleNamespace(file_size=101*1024*1024)]):
                with self.assertRaisesRegex(ValueError,'解压'):parse(file,'bad.xlsx','x')
    def test_dense_cache_isolates_dimensions_and_sources(self):
        rows=[(SimpleNamespace(id='a'),SimpleNamespace(created_at=1,embedding_dim=2,embedding_model='m',embedding_json='[1,0]'))]
        self.assertAlmostEqual(dense_scores(rows,[1,0],'m','database')['a'],1)
        self.assertEqual(dense_scores(rows,[1,0,0],'m','database'),{})
        self.assertEqual(dense_scores([], [1,0],'m','database'),{})

    def test_production_schema_uses_migrations_and_rejects_unversioned_database(self):
        from app.core.config import settings
        from app.db.init_db import init_db
        from sqlalchemy import create_engine, text
        with tempfile.TemporaryDirectory() as folder:
            url='sqlite:///'+str(Path(folder)/'new.db');engine=create_engine(url)
            with patch.object(settings,'app_env','production'),patch.object(settings,'database_url',url),patch('app.db.init_db.engine',engine):
                init_db()
            with engine.connect() as conn:
                self.assertEqual(conn.execute(text('SELECT version_num FROM alembic_version')).scalar(),'0006_agent_traces')
            engine.dispose()
            other=create_engine('sqlite:///'+str(Path(folder)/'legacy.db'))
            with other.begin() as conn:conn.execute(text('CREATE TABLE legacy(id INTEGER)'))
            with patch.object(settings,'app_env','production'),patch('app.db.init_db.engine',other):
                with self.assertRaisesRegex(RuntimeError,'no migration version'):init_db()
            other.dispose()
