"""Exercise frontend-only deployment/rollback with isolated filesystem and fake Docker."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
VERSION = 'frontend-v0.2.0-abcdef123456'
IMAGE_ID = 'sha256:' + 'a' * 64
OLD_IMAGE_ID = 'sha256:' + 'b' * 64


class FrontendDeployTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.incoming = self.root / 'incoming'
        self.incoming.mkdir()
        (self.root / 'deploy').mkdir()
        self.state = self.root / 'deploy/company-version.env'
        self.previous = 'KB_VERSION=old\nKB_BACKEND_VERSION=backend-old\nKB_FRONTEND_VERSION=frontend-old\n'
        self.state.write_text(self.previous)
        (self.root / 'deploy/compose.company.yaml').touch()
        (self.incoming / 'images.tar').touch()
        (self.incoming / 'manifest.json').write_text('{"release":"new"}')
        (self.incoming / 'check-frontend.sh').write_text('#!/bin/bash\n[[ "${FAIL_HEALTH:-0}" == 0 ]]\n')
        script = (SCRIPTS / 'frontend-apply.sh').read_text().replace(
            'root=/opt/knowledge-base', f'root="{self.root}"')
        (self.incoming / 'apply.sh').write_text(script)
        binaries = self.root / 'bin'
        binaries.mkdir()
        for name, body in {
            'flock': 'exit 0',
            'sha256sum': 'exit 0',
            'docker': f'''echo "$*" >> "$DOCKER_LOG"
if [[ "$1 $2" == 'image inspect' ]]; then
  case "$*" in
    *Architecture*) echo amd64 ;;
    *frontend-old*) echo '{OLD_IMAGE_ID}' ;;
    *) echo '{IMAGE_ID}' ;;
  esac
elif [[ "$1" == compose ]]; then
  if [[ "$*" == *'ps -q web'* ]]; then echo old-web; fi
elif [[ "$1" == create ]]; then echo asset-container
fi''',
        }.items():
            p = binaries / name
            p.write_text('#!/bin/bash\nset -e\n' + body + '\n')
            p.chmod(0o755)
        self.env = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ['PATH'],
                        DOCKER_LOG=str(self.root / 'docker.log'))

    def run_apply(self, mode='apply', **env):
        return subprocess.run(['bash', 'apply.sh', VERSION, 'https://frontend.example', IMAGE_ID, mode],
                              cwd=self.incoming, env={**self.env, **env}, capture_output=True, text=True)

    def assert_frontend_only(self):
        log = (self.root / 'docker.log').read_text()
        self.assertNotIn('stop backend', log)
        self.assertNotIn(' up -d --wait', log)
        self.assertIn('up -d --no-deps --wait --wait-timeout 120 web', log)
        self.assertIn('KB_BACKEND_VERSION=backend-old', self.state.read_text())

    def test_success_updates_only_frontend_and_keeps_rollback_state(self):
        result = self.run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f'KB_FRONTEND_VERSION={VERSION}', self.state.read_text())
        self.assertEqual((self.incoming / 'previous-version.env').read_text(), self.previous)
        self.assertFalse((self.incoming / 'images.tar').exists())
        self.assert_frontend_only()

    def test_failed_health_restores_previous_version(self):
        result = self.run_apply(FAIL_HEALTH='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.state.read_text(), self.previous)
        self.assertIn('rolled back', result.stderr)
        self.assert_frontend_only()

    def test_external_check_can_request_rollback_and_stale_rollback_is_rejected(self):
        self.assertEqual(self.run_apply().returncode, 0)
        result = self.run_apply('rollback')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.state.read_text(), self.previous)
        result = self.run_apply('rollback')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Refusing stale rollback', result.stderr)
