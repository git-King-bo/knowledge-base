"""Deterministic business ordering shared by initial searches and snapshot sorts."""
from datetime import datetime, timezone


def recency_key(fields):
    for field in ('上次自动更新时间','更新时间','updated_at'):
        raw=str(fields.get(field,'')).strip().replace('/','-')
        if not raw:
            continue
        try:
            value=datetime.fromisoformat(raw.replace('Z','+00:00'))
            if value.tzinfo is None:value=value.replace(tzinfo=timezone.utc)
            return -value.timestamp()
        except (ValueError,OverflowError):
            continue
    return float('inf')
