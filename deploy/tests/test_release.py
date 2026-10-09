import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

spec = importlib.util.spec_from_file_location('release', Path(__file__).resolve().parents[1] / 'release.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


class ReleaseTests(unittest.TestCase):
    def test_slow_image_pull_reports_progress(self):
        process=Mock(returncode=0)
        process.communicate.side_effect=[r.subprocess.TimeoutExpired('docker',30),('done','')]
        process.poll.return_value=0
        with patch.object(r.subprocess,'Popen',return_value=process),patch('builtins.print') as log:
            r.pull_image('ghcr.io/example@sha256:abc')
        self.assertTrue(any('still running' in str(call) for call in log.call_args_list))
        process.kill.assert_not_called()

    def test_image_pull_timeout_stops_only_pull_client(self):
        process=Mock()
        process.poll.return_value=None
        with patch.object(r.subprocess,'Popen',return_value=process), \
             patch.object(r.time,'monotonic',side_effect=[0,2]),patch('builtins.print'):
            with self.assertRaisesRegex(RuntimeError,'exceeded'):
                r.pull_image('image',timeout=1)
        process.kill.assert_called_once()
        process.communicate.assert_called_once()

    def test_registry_error_does_not_expose_signed_urls(self):
        process=Mock(returncode=1)
        process.communicate.return_value=('', 'https://registry.example/blob?secret=value')
        process.poll.return_value=1
        with patch.object(r.subprocess,'Popen',return_value=process),patch('builtins.print') as log:
            with self.assertRaisesRegex(RuntimeError,'Image download failed') as error:
                r.pull_image('image')
        self.assertNotIn('secret',str(error.exception)+str(log.call_args_list))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        (root / 'deploy').mkdir()
        (root / 'deploy/Caddyfile.ecs').write_text('original')
        self.release = r.Releases(root)
        self.release.state.update(active='old', previous='older', candidate='new', token='a'*48)
        self.release.save()

    def test_manifest_rejects_mutable_images_and_wrong_repository(self):
        valid = dict(version='sha-123abc', commit='a'*40,
                     backend='ghcr.io/git-king-bo/knowledge-base/backend@sha256:'+'b'*64,
                     frontend='ghcr.io/git-king-bo/knowledge-base/frontend@sha256:'+'c'*64)
        self.assertEqual(r.validate_manifest(valid), valid)
        for invalid in ['backend:latest', 'evil.example/backend@sha256:'+'b'*64,
                        valid['frontend'], 'sha256:'+'b'*64]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                r.validate_manifest(dict(valid, backend=invalid))
        with self.assertRaises(ValueError):
            r.validate_manifest(dict(valid, version='../active'))

    def test_cookie_routes_frontend_and_api_together(self):
        text = self.release.config('old', 'new', 'a'*48)
        self.assertIn('kb-web-new:8080', text)
        self.assertIn('kb-web-old:8080', text)
        self.assertIn('HttpOnly; SameSite=Strict', text)
        self.assertNotIn('kb-api-new', text)
        with self.assertRaises(ValueError):
            self.release.config('old','new','injected\n}')

    def test_failed_promotion_recovers_state_and_does_not_restore_database(self):
        deploy = self.release
        events=[]
        with patch.object(deploy,'ensure'), patch.object(deploy,'backup') as backup, \
             patch.object(deploy,'launch',side_effect=lambda role,v:events.append(('launch',role,v))), \
             patch.object(deploy,'healthy'), patch.object(deploy,'route',side_effect=RuntimeError('bad edge')), \
             patch.object(deploy,'remove',side_effect=lambda name:events.append(('remove',name))), patch.object(r,'run'):
            with self.assertRaisesRegex(RuntimeError,'bad edge'):
                deploy.switch('new')
        self.assertEqual(deploy.state['active'],'old')
        self.assertEqual(deploy.state['candidate'],'new')
        self.assertIn(('launch','worker','old'),events)
        self.assertIn(('remove','kb-worker-new'),events)
        self.assertFalse(deploy.journal.exists())
        self.assertEqual(deploy.edge_file.read_text(),'original')
        backup.assert_called_once()

    def test_promotion_stops_previous_worker_before_new_worker(self):
        deploy=self.release
        events=[]
        with patch.object(deploy,'ensure'),patch.object(deploy,'backup'),patch.object(deploy,'healthy'), \
             patch.object(deploy,'route'),patch.object(deploy,'launch',side_effect=lambda *a: events.append(('launch',)+a)), \
             patch.object(r,'run',side_effect=lambda *a,**kw: events.append(a)):
            deploy.switch('new')
        self.assertLess(events.index(('docker','stop','--time','300','kb-worker-old')),
                        events.index(('launch','worker','new')))
        self.assertEqual(deploy.state['active'],'new')
        self.assertEqual(deploy.state['previous'],'old')
        self.assertIsNone(deploy.state['candidate'])
        self.assertFalse(deploy.journal.exists())

    def test_failed_candidate_keeps_active_routing(self):
        deploy=self.release
        deploy.state['candidate']=None
        with patch.object(deploy,'retire'),patch.object(deploy,'ensure',side_effect=RuntimeError('schema mismatch')), \
             patch.object(deploy,'remove'),patch.object(deploy,'route') as route:
            with self.assertRaises(RuntimeError):deploy.stage('new')
        route.assert_not_called()
        self.assertEqual(deploy.state['active'],'old')
        self.assertIsNone(deploy.state['candidate'])

    def test_runtime_always_uses_shared_mysql_and_check_only_migrations(self):
        args=self.release.backend_args('new')
        self.assertIn('APP_DATABASE_MODE=mysql',args)
        self.assertIn('APP_MIGRATION_MODE=check',args)
        self.assertIn('APP_WORKER_ENABLED=false',args)
        self.assertIn('APP_WORKER_ENABLED=true',self.release.backend_args('new',worker=True))

    def test_abort_keeps_active_worker_and_database(self):
        deploy=self.release
        with patch.object(deploy,'route') as route, patch.object(deploy,'remove') as remove:
            deploy.abort()
        route.assert_called_once_with('old')
        self.assertEqual({c.args[0] for c in remove.call_args_list},{'kb-api-new','kb-web-new'})
        self.assertEqual(deploy.state['active'],'old')


if __name__=='__main__':unittest.main()
