"""Run from backend: .venv/bin/python scripts/import_talents.py --source-id ID [--apply]."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, select
from app.db.models import KnowledgeSourceModel, TalentModel
from app.services.talent_import import read_talents


def import_records(engine, records):
    # Validate existing source rows before adding anything; never overwrite edited data.
    inserted = 0
    with engine.begin() as conn:
        TalentModel.__table__.create(conn, checkfirst=True)
        for record in records:
            existing = conn.execute(select(TalentModel.__table__).where(
                TalentModel.id == record['id'])).mappings().first()
            if existing:
                if any(existing[key] != value for key, value in record.items()):
                    raise ValueError(f"Existing record differs at row {record['source_row']}")
                continue
            conn.execute(TalentModel.__table__.insert().values(
                **record, created_at=datetime.now(timezone.utc)))
            inserted += 1
    return inserted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=Path('knowledge_base.db'))
    parser.add_argument('--source-id', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    database = args.database.resolve(strict=True)
    engine = create_engine(f'sqlite:///{database}')
    with engine.connect() as conn:
        source = conn.execute(select(KnowledgeSourceModel.__table__).where(
            KnowledgeSourceModel.id == args.source_id)).mappings().one()
    path = Path(source['storage_path'])
    if not path.is_absolute():
        path = database.parent / path
    records = read_talents(path, args.source_id)
    if not records:
        raise ValueError('No talent records found')
    names = Counter(r['name'] for r in records)
    summary = dict(source_id=args.source_id, rows=len(records),
                   distinct_names=len(names), duplicate_name_groups=sum(n > 1 for n in names.values()))
    if args.apply:
        backup = database.parent / 'storage' / 'backups' / (
            f"before-talents-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}.db")
        backup.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as src, sqlite3.connect(backup) as dst:
            src.backup(dst)
        summary['backup'] = str(backup)
        summary['inserted'] = import_records(engine, records)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    engine.dispose()


if __name__ == '__main__':
    main()
