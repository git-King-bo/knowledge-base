import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

DEPLOY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEPLOY))
import release


def load(name):
    spec = importlib.util.spec_from_file_location(name, DEPLOY / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


transfer = load('image-transfer')
sender = load('send-release')
entry = load('ssh-release')
IMAGE_ID = 'sha256:' + 'a' * 64


def manifest():
    return dict(version='test-offline', commit='b' * 40,
                backend='ghcr.io/git-king-bo/knowledge-base/backend@sha256:' + 'c' * 64,
                frontend='ghcr.io/git-king-bo/knowledge-base/frontend@sha256:' + 'd' * 64,
                image_ids={'backend': IMAGE_ID, 'frontend': 'sha256:' + 'e' * 64})


class TransferTests(unittest.TestCase):
    def test_only_verified_complete_archive_is_loaded(self):
        data = b'archive payload'
        header = dict(image_id=IMAGE_ID, size=len(data), sha256=hashlib.sha256(data).hexdigest())
        for payload, checksum in ((data[:-1], header['sha256']), (data, '0' * 64)):
            with self.subTest(payload=payload), patch.object(transfer.subprocess, 'run') as run:
                with self.assertRaises(ValueError):
                    transfer.receive(io.BytesIO(payload), dict(header, sha256=checksum))
                run.assert_not_called()
        with patch.object(transfer.subprocess, 'run') as run, patch.object(transfer, 'present', return_value=True):
            transfer.receive(io.BytesIO(data), header)
            self.assertEqual(run.call_args.args[0][:3], ['docker', 'load', '--quiet'])

    def test_import_must_contain_expected_image(self):
        data = b'archive'
        header = dict(image_id=IMAGE_ID, size=len(data), sha256=hashlib.sha256(data).hexdigest())
        with patch.object(transfer.subprocess, 'run'), patch.object(transfer, 'present', return_value=False):
            with self.assertRaisesRegex(ValueError, 'Expected image missing'):
                transfer.receive(io.BytesIO(data), header)

    def test_rejects_unbounded_input(self):
        for line in (b'a' * 8193, b'{}'):
            with self.assertRaises(ValueError):
                transfer.read_header(io.BytesIO(line))
        with self.assertRaises(ValueError):
            transfer.receive(io.BytesIO(), dict(image_id=IMAGE_ID, size=transfer.MAX_ARCHIVE + 1))

    def test_offline_register_uses_local_ids_and_keeps_registry_provenance(self):
        value = manifest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'deploy').mkdir()
            (root / 'deploy/production.env').write_text('TEST=1')
            source = root / 'manifest.json'
            source.write_text(json.dumps(value))
            deploy = release.Releases(root)
            with patch.object(release, 'pull_image') as pull, patch.object(release, 'run', return_value='[{"Architecture":"amd64","Os":"linux"}]') as run:
                deploy.register(source)
                pull.assert_not_called()
                self.assertEqual([call.args[-1] for call in run.call_args_list], list(value['image_ids'].values()))
            self.assertEqual(deploy.manifest(value['version']), value)
            self.assertEqual(release.image_reference(value, 'backend'), IMAGE_ID)
            legacy = {k: v for k, v in value.items() if k != 'image_ids'}
            self.assertEqual(release.image_reference(legacy, 'backend'), legacy['backend'])

    def test_offline_manifest_cannot_bypass_repository_or_id_validation(self):
        value = manifest()
        for bad in (dict(value, backend='untrusted:latest'),
                    dict(value, image_ids={'backend': IMAGE_ID}),
                    dict(value, image_ids=dict(backend='latest', frontend=IMAGE_ID))):
            with self.assertRaises(ValueError):
                release.validate_manifest(bad)

    def test_failed_registration_does_not_stage(self):
        with patch.dict(entry.os.environ, SSH_ORIGINAL_COMMAND='kb-release stage-offline test-offline'), \
             patch.object(entry.sys, 'stdin', io.StringIO(json.dumps(manifest()))), \
             patch.object(entry.subprocess, 'run', side_effect=entry.subprocess.CalledProcessError(1, 'register')) as run:
            with self.assertRaises(entry.subprocess.CalledProcessError):
                entry.main()
        self.assertEqual(run.call_count, 1)
        self.assertIn('register', run.call_args.args[0])

    def test_cached_images_are_not_exported_or_sent(self):
        value = manifest()
        def checked(args, **kwargs):
            from types import SimpleNamespace
            if args[:3] == ['docker', 'image', 'inspect']:
                role = 'backend' if '/backend@' in args[-1] else 'frontend'
                return SimpleNamespace(stdout=json.dumps([dict(Id=value['image_ids'][role], Architecture='amd64', Os='linux')]))
            return SimpleNamespace(stdout='{"missing": []}')
        with tempfile.TemporaryDirectory() as folder, patch.object(sender, 'checked', side_effect=checked) as run:
            delivered = sender.deliver(value, ['ssh'], Path(folder))
        self.assertEqual(delivered, value)
        self.assertFalse(any('save' in c.args[0] or 'kb-release image-import' in c.args[0] for c in run.call_args_list))


if __name__ == '__main__':
    unittest.main()
