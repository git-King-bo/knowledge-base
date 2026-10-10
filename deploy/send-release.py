#!/usr/bin/env python3
"""CI runner downloads immutable images and transfers missing images over SSH."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from release import validate_manifest


def checked(*args, **kwargs):
    return subprocess.run(*args, check=True, **kwargs)


def deliver(manifest, ssh, folder):
    validate_manifest(manifest)
    ids = {}
    for role in ('backend', 'frontend'):
        print('Runner downloading {} image (linux/amd64)...'.format(role), flush=True)
        checked(['docker', 'pull', '--platform', 'linux/amd64', manifest[role]], timeout=300)
        info = json.loads(checked(['docker', 'image', 'inspect', manifest[role]],
                                 stdout=subprocess.PIPE, universal_newlines=True).stdout)[0]
        if info['Architecture'] != 'amd64' or info['Os'] != 'linux':
            raise ValueError('Expected linux/amd64 image')
        ids[role] = info['Id']
    manifest = dict(manifest, image_ids=ids)
    validate_manifest(manifest)
    result = checked(ssh + ['kb-release image-status'],
                     input=json.dumps({'images': list(ids.values())}) + '\n',
                     stdout=subprocess.PIPE, universal_newlines=True, timeout=45)
    missing = json.loads(result.stdout)['missing']
    if not isinstance(missing, list) or not set(missing).issubset(set(ids.values())):
        raise ValueError('Invalid image cache response')
    for role, image_id in ids.items():
        if image_id not in missing:
            print('Server already has {}; skipping transfer.'.format(role), flush=True)
            continue
        archive = folder / 'image.tar'
        compressed = folder / 'image.tar.gz'
        # Save by ID to avoid overwriting any existing server tags during load.
        checked(['docker', 'save', '--output', str(archive), image_id], timeout=180)
        with archive.open('rb') as source, gzip.open(str(compressed), 'wb', compresslevel=1) as target:
            shutil.copyfileobj(source, target)
        archive.unlink()
        digest = hashlib.sha256()
        with compressed.open('rb') as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(chunk)
        header = dict(image_id=image_id, size=compressed.stat().st_size, sha256=digest.hexdigest())
        # A file-backed envelope bounds memory and gives SSH an ordinary streaming stdin.
        with tempfile.TemporaryFile() as envelope:
            envelope.write((json.dumps(header) + '\n').encode())
            with compressed.open('rb') as source:
                shutil.copyfileobj(source, envelope)
            envelope.seek(0)
            print('Sending {}: {:.1f} MiB over SSH'.format(role, header['size'] / 1024 ** 2), flush=True)
            checked(ssh + ['kb-release image-import'], stdin=envelope, timeout=660)
        compressed.unlink()
    return manifest


def main():
    env = os.environ
    action, version = env['ACTION'], env['VERSION']
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        key, hosts = folder / 'key', folder / 'known_hosts'
        key.write_text(env['DEPLOY_SSH_KEY'] + '\n')
        key.chmod(0o600)
        hosts.write_text(env['DEPLOY_KNOWN_HOSTS'] + '\n')
        ssh = ['ssh', '-T', '-i', str(key), '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
               '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(hosts),
               '-o', 'ConnectTimeout=20', '-o', 'ServerAliveInterval=15',
               '-o', 'ServerAliveCountMax=4', 'root@120.27.205.41']
        payload = ''
        if action in ('stage', 'bootstrap'):
            manifest = json.loads(Path('release-artifact/release.json').read_text())
            validate_manifest(manifest)
            if manifest['version'] != version:
                raise ValueError('Artifact version mismatch')
            manifest = deliver(manifest, ssh, folder)
            payload = json.dumps(manifest)
            action += '-offline'
        command = 'kb-release ' + action
        if action not in ('status', 'abort', 'retire'):
            command += ' ' + version
        checked(ssh + [command], input=payload, universal_newlines=True, timeout=900)


if __name__ == '__main__':
    main()
