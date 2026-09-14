"""Token analytics over all matching calls; pagination affects only the detail table."""
import csv
import io
from datetime import datetime, time, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db.models import AIActivityLogModel as Log, TokenUsageModel as Usage
from app.db.session import get_db

router = APIRouter()


class UsageFilter:
    def __init__(
        self,
        days: int = Query(default=7, ge=1, le=90),
        provider_id: str | None = None,
        model: str | None = None,
        action: Literal['ask', 'chat', 'embedding'] | None = None,
        knowledge_base_id: str | None = None,
        timezone_offset: int = Query(default=480, ge=-720, le=840),
    ):
        self.days = days
        self.offset = timezone_offset
        local_today = (datetime.now(timezone.utc) + timedelta(minutes=timezone_offset)).date()
        self.start_date = local_today - timedelta(days=days - 1)
        start = datetime.combine(self.start_date, time.min) - timedelta(minutes=timezone_offset)
        end = datetime.combine(local_today + timedelta(days=1), time.min) - timedelta(minutes=timezone_offset)
        self.conditions = [Log.created_at >= start, Log.created_at < end,
                           Log.action.in_(['ask', 'chat', 'embedding'])]
        for column, value in [(Log.provider_id, provider_id), (Log.model, model),
                              (Log.action, action), (Usage.knowledge_base_id, knowledge_base_id)]:
            if value:
                self.conditions.append(column == value)

    def query(self):
        return select(
            Log.id, Log.created_at, Log.action, Log.provider_id, Log.model,
            Log.success, Log.latency_ms, Usage.input_tokens, Usage.output_tokens,
            Usage.total_tokens, Usage.cached_tokens, Usage.knowledge_base_id,
            func.coalesce(Usage.source, 'unknown').label('source'),
        ).outerjoin(Usage, Usage.log_id == Log.id).where(*self.conditions)


def metrics(table):
    return [
        func.count().label('requests'),
        func.coalesce(func.sum(case((table.c.success.is_(False), 1), else_=0)), 0).label('failures'),
        func.coalesce(func.sum(table.c.input_tokens), 0).label('input_tokens'),
        func.coalesce(func.sum(table.c.output_tokens), 0).label('output_tokens'),
        func.coalesce(func.sum(table.c.total_tokens), 0).label('total_tokens'),
        func.coalesce(func.sum(table.c.cached_tokens), 0).label('cached_tokens'),
        func.coalesce(func.sum(case((table.c.total_tokens.is_(None), 1), else_=0)), 0).label('unknown_requests'),
        func.coalesce(func.avg(table.c.latency_ms), 0).label('avg_latency_ms'),
    ]


def serialize_record(record):
    result = dict(record)
    result['created_at'] = result['created_at'].replace(tzinfo=timezone.utc).isoformat()
    return result


@router.get('')
def overview(
    filters: UsageFilter = Depends(),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    table = filters.query().subquery()
    summary = dict(db.execute(select(*metrics(table))).mappings().one())
    # Database stores UTC. Bucket in the viewer's timezone, including empty dates.
    day = func.date(func.datetime(table.c.created_at, f'{filters.offset:+d} minutes'))
    points = {row['date']: dict(row) for row in db.execute(
        select(day.label('date'), *metrics(table)).group_by(day).order_by(day)
    ).mappings()}
    daily = []
    for offset in range(filters.days):
        key = (filters.start_date + timedelta(days=offset)).isoformat()
        daily.append(points.get(key, {'date': key, **{name: 0 for name in summary}}))
    models = [dict(row) for row in db.execute(
        select(table.c.provider_id, table.c.model, *metrics(table))
        .group_by(table.c.provider_id, table.c.model)
        .order_by(func.coalesce(func.sum(table.c.total_tokens), 0).desc())
    ).mappings()]
    records = db.execute(filters.query().order_by(Log.created_at.desc(), Log.id)
                         .offset((page - 1) * page_size).limit(page_size)).mappings()
    return {'summary': summary, 'daily': daily, 'models': models,
            'records': [serialize_record(row) for row in records],
            'page': page, 'page_size': page_size, 'total': summary['requests'],
            'timezone_offset': filters.offset}


@router.get('/export')
def export_usage(filters: UsageFilter = Depends(), db: Session = Depends(get_db)):
    output = io.StringIO()
    writer = csv.writer(output)
    fields = ['id', 'created_at', 'action', 'provider_id', 'model', 'success',
              'input_tokens', 'output_tokens', 'total_tokens', 'cached_tokens',
              'source', 'latency_ms', 'knowledge_base_id']
    writer.writerow(fields)
    for row in db.execute(filters.query().order_by(Log.created_at.desc(), Log.id)).mappings():
        record = serialize_record(row)
        values = [record[field] for field in fields]
        # Keep spreadsheet applications from executing provider/model names as formulas.
        writer.writerow(["'" + value if isinstance(value, str) and value.startswith(('=', '+', '-', '@', '\t', '\r'))
                         else value for value in values])
    return Response('\ufeff' + output.getvalue(), media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="token-usage.csv"'})
