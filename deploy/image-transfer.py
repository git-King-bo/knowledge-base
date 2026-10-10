#!/usr/bin/env python3
"""Restricted SSH image cache/import protocol; never activates a release."""
import hashlib
import json
import signal
import subprocess
import sys
import tempfile

from release import LOCAL_IMAGE

MAX_ARCHIVE = 2 * 1024 ** 3


def read_header(stream):
    line = stream.readline(8193)
    if len(line) > 8192 or not line.endswith(b'\n'):
        raise ValueError('Invalid transfer header')
    return json.loads(line.decode('utf-8'))


def validate_id(value):
    if not isinstance(value, str) or not LOCAL_IMAGE.fullmatch(value):
        raise ValueError('Invalid image ID')


def present(image_id):
    validate_id(image_id)
    result = subprocess.run(['docker', 'image', 'inspect', image_id],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
    return result.returncode == 0


def receive(stream, header):
    validate_id(header['image_id'])
    size = header['size']
    if type(size) is not int or not 0 < size <= MAX_ARCHIVE:
        raise ValueError('Archive size exceeds limit')
    digest = hashlib.sha256()
    with tempfile.NamedTemporaryFile(prefix='kb-image-', suffix='.tar.gz') as archive:
        received = 0
        report_at = 0
        while received < size:
            chunk = stream.read(min(1024 * 1024, size - received))
            if not chunk:
                raise ValueError('Image transfer interrupted; site unchanged')
            archive.write(chunk)
            digest.update(chunk)
            received += len(chunk)
            if received >= report_at or received == size:
                print('Image transfer: {} / {} MiB'.format(received // 1024 ** 2,
                                                          size // 1024 ** 2), flush=True)
                report_at = received + 8 * 1024 ** 2
        if digest.hexdigest() != header['sha256']:
            raise ValueError('Image archive checksum mismatch')
        archive.flush()
        print('Checksum verified; importing image...', flush=True)
        subprocess.run(['docker', 'load', '--quiet', '--input', archive.name], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
    if not present(header['image_id']):
        raise ValueError('Expected image missing after import')
    print('Image imported: ' + header['image_id'], flush=True)


def main(action):
    def timed_out(*args):
        raise RuntimeError('Image transfer exceeded 10 minutes; site unchanged')
    signal.signal(signal.SIGALRM, timed_out)
    signal.alarm(600)
    try:
        header = read_header(sys.stdin.buffer)
        if action == 'image-status':
            ids = header['images']
            if not isinstance(ids, list) or len(ids) != 2:
                raise ValueError('Expected two image IDs')
            print(json.dumps({'missing': [i for i in ids if not present(i)]}), flush=True)
        else:
            receive(sys.stdin.buffer, header)
    finally:
        signal.alarm(0)


if __name__ == '__main__':
    main(sys.argv[1])
