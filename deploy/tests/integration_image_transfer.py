"""Tiny real Docker save/gzip/SSH receiver/load round trip; no production access."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import uuid


def run(*args, **kwargs):
    return subprocess.run(list(args), check=True, stdout=subprocess.PIPE, **kwargs).stdout


def main():
    payload = uuid.uuid4().hex.encode()
    source = io.BytesIO()
    with tarfile.open(fileobj=source, mode='w') as archive:
        member = tarfile.TarInfo('transfer-test')
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
    image_id = run('docker', 'import', '--platform', 'linux/amd64', '-', input=source.getvalue()).decode().strip()
    try:
        archive = gzip.compress(run('docker', 'save', image_id))
        run('docker', 'image', 'rm', image_id)
        header = dict(image_id=image_id, size=len(archive), sha256=hashlib.sha256(archive).hexdigest())
        envelope = (json.dumps(header) + '\n').encode() + archive
        receiver = Path(__file__).resolve().parents[1] / 'image-transfer.py'
        result = run(sys.executable, str(receiver), 'image-import', input=envelope)
        print(result.decode())
        info = json.loads(run('docker', 'image', 'inspect', image_id))[0]
        assert info['Id'] == image_id and info['Architecture'] == 'amd64'
        cached = run(sys.executable, str(receiver), 'image-status',
                     input=(json.dumps({'images': [image_id, image_id]}) + '\n').encode())
        assert json.loads(cached)['missing'] == []
        print('Real Docker image transfer and cache check passed.')
    finally:
        subprocess.run(['docker', 'image', 'rm', image_id], stdout=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
