import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from app.services.retrieval_cache import dense_scores,_cache,_lock

class DenseCacheTests(unittest.TestCase):
    def setUp(self):
        with _lock:_cache.clear()

    def rows(self,ids=('a','b'),version=1):
        return [(SimpleNamespace(id=i),SimpleNamespace(created_at=version,embedding_dim=2,embedding_model='m')) for i in ids]

    def test_warm_queries_do_not_fetch_vectors_and_recompute_scores(self):
        loader=Mock(return_value={'a':'[1,0]','b':'[0,1]'})
        first=dense_scores(self.rows(),[1,0],'m','db',load_vectors=loader)
        second=dense_scores(self.rows(),[0,1],'m','db',load_vectors=loader)
        self.assertEqual(loader.call_count,1)
        self.assertEqual(first,{'a':1.0,'b':0.0})
        self.assertEqual(second,{'a':0.0,'b':1.0})

    def test_index_changes_and_access_scopes_invalidate_cache(self):
        loader=Mock(return_value={'a':'[1,0]','b':'[0,1]'})
        dense_scores(self.rows(),[1,0],'m','db',load_vectors=loader)
        dense_scores(self.rows(version=2),[1,0],'m','db',load_vectors=loader)
        scoped=dense_scores(self.rows(ids=('b',),version=2),[1,0],'m','db',load_vectors=loader)
        dense_scores(self.rows(ids=('b',),version=2),[1,0],'m','other-db',load_vectors=loader)
        self.assertEqual(loader.call_count,4)
        self.assertEqual(set(scoped),{'b'})

    def test_loaded_and_legacy_paths_produce_same_scores(self):
        rows=self.rows()
        for r,e in rows:e.embedding_json='[1,2]' if r.id=='a' else '[3,1]'
        expected=dense_scores(rows,[2,1],'m','legacy')
        actual=dense_scores(self.rows(),[2,1],'m','new',load_vectors=lambda:{r.id:e.embedding_json for r,e in rows})
        self.assertEqual(actual,expected)

    def test_disk_cache_survives_memory_reset_and_checks_scope_and_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            loader=Mock(return_value={'a':'[1,0]','b':'[0,1]'})
            dense_scores(self.rows(),[1,0],'m','db',load_vectors=loader,cache_dir=directory)
            with _lock:_cache.clear()
            scores=dense_scores(self.rows(),[0,1],'m','db',load_vectors=loader,cache_dir=directory)
            self.assertEqual(loader.call_count,1)
            self.assertEqual(scores,{'a':0.0,'b':1.0})
            dense_scores(self.rows(ids=('b',)),[0,1],'m','db',load_vectors=loader,cache_dir=directory)
            dense_scores(self.rows(version=2),[0,1],'m','db',load_vectors=loader,cache_dir=directory)
            dense_scores(self.rows(),[0,1],'m','other-db',load_vectors=loader,cache_dir=directory)
            self.assertEqual(loader.call_count,4)

    def test_corrupt_disk_cache_falls_back_to_database(self):
        with tempfile.TemporaryDirectory() as directory:
            loader=Mock(return_value={'a':'[1,0]','b':'[0,1]'})
            dense_scores(self.rows(),[1,0],'m','db',load_vectors=loader,cache_dir=directory)
            with _lock:_cache.clear()
            next(Path(directory).glob('*.npz')).write_bytes(b'broken')
            self.assertEqual(dense_scores(self.rows(),[1,0],'m','db',load_vectors=loader,cache_dir=directory),{'a':1.0,'b':0.0})
            self.assertEqual(loader.call_count,2)
