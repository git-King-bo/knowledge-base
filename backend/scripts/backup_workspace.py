"""Consistent SQLite snapshot plus referenced immutable files, with checksum verification.

Run from backend. Restore always writes to a NEW directory; stop service before switching it in.
Encryption key must be backed up separately, never alongside this archive.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tarfile
import tempfile


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def backup(database,output):
    database=database.resolve(strict=True)
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder);snapshot=root/'knowledge_base.db'
        with sqlite3.connect(f'file:{database}?mode=ro',uri=True) as src,sqlite3.connect(snapshot) as dst:src.backup(dst)
        with sqlite3.connect(snapshot) as db:
            for sid,value in db.execute('SELECT id,storage_path FROM knowledge_sources'):
                source=Path(value)
                if not source.is_absolute():source=database.parent/source
                relative=Path('storage/uploads')/f'{sid}-{source.name}'
                target=root/relative;target.parent.mkdir(parents=True,exist_ok=True)
                if not source.is_file():raise FileNotFoundError(f'Missing source file: {sid}')
                shutil.copy2(source,target)
                db.execute('UPDATE knowledge_sources SET storage_path=? WHERE id=?',(str(relative),sid))
            db.commit()
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Database integrity check failed')
        manifest={str(p.relative_to(root)):sha(p) for p in root.rglob('*') if p.is_file()}
        (root/'manifest.json').write_text(json.dumps(manifest,indent=2))
        temporary=output.with_suffix(output.suffix+'.partial')
        with tarfile.open(temporary,'w:gz') as archive:
            for p in root.rglob('*'):
                if p.is_file():archive.add(p,arcname=str(p.relative_to(root)))
        temporary.replace(output)
    return output


def restore(archive,target):
    if target.exists():raise ValueError('Restore target must be a new directory')
    target.mkdir(parents=True)
    with tarfile.open(archive,'r:gz') as tar:
        for member in tar.getmembers():
            if not member.isfile() or Path(member.name).is_absolute() or '..' in Path(member.name).parts:
                raise ValueError('Unsafe archive member')
        tar.extractall(target,filter='data')
    manifest=json.loads((target/'manifest.json').read_text())
    for name,expected in manifest.items():
        if Path(name).is_absolute() or '..' in Path(name).parts:raise ValueError('Unsafe manifest')
        if sha(target/name)!=expected:raise ValueError(f'Checksum mismatch: {name}')
    with sqlite3.connect(target/'knowledge_base.db') as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Database integrity check failed')
    return target

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['backup','restore'])
    p.add_argument('--database',type=Path,default=Path('knowledge_base.db'))
    p.add_argument('--archive',type=Path);p.add_argument('--target',type=Path)
    args=p.parse_args()
    if args.action=='backup':
        output=args.archive or Path('storage/backups')/datetime.now(timezone.utc).strftime('workspace-%Y%m%dT%H%M%S.tar.gz')
        print(backup(args.database,output))
    else:
        if not args.archive or not args.target:p.error('restore requires --archive and --target')
        print(restore(args.archive,args.target))
