"""Conversation-scoped observability; old uncorrelated logs are never guessed."""
import json
from datetime import timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.orm import Session, defer
from app.core.security import actor
from app.db.session import get_db
from app.db.models import AgentTraceModel as Trace, SavedConversationModel, BaseAccessModel

router = APIRouter()

def visibility(db):
    user = actor.get()
    if not user:
        # Development without authentication only sees anonymous requests.
        return [Trace.user_id.is_(None)]
    conditions = [Trace.user_id == user.id]
    if user.role != 'admin':
        bases = select(BaseAccessModel.base_id).where(BaseAccessModel.user_id == user.id)
        conditions.append(Trace.knowledge_base_id.in_(bases))
    return conditions

def summary(item):
    return dict(id=item.id, conversation_id=item.conversation_id, turn_id=item.turn_id,
        question=item.question, status=item.status, created_at=item.created_at.replace(tzinfo=timezone.utc).isoformat(),
        duration_ms=item.duration_ms, first_token_ms=item.first_token_ms, knowledge_base_id=item.knowledge_base_id,
        call_count=item.call_count, unknown_calls=item.unknown_calls, total_tokens=item.total_tokens,
        input_tokens=item.input_tokens, output_tokens=item.output_tokens, cached_tokens=item.cached_tokens)

@router.get('/conversations')
def conversations(db: Session = Depends(get_db)):
    user = actor.get()
    saved = list(db.scalars(select(SavedConversationModel).where(
        SavedConversationModel.user_id == user.id if user else False).order_by(SavedConversationModel.updated_at.desc()).limit(100)))
    items = {item.id: {'id': item.id, 'title': item.title, 'has_traces': False} for item in saved}
    latest = select(Trace.conversation_id, func.max(Trace.created_at).label('latest')).where(
        *visibility(db), Trace.conversation_id.is_not(None)).group_by(Trace.conversation_id).subquery()
    traces = db.execute(select(Trace.conversation_id, Trace.question).join(latest,
        (Trace.conversation_id == latest.c.conversation_id) & (Trace.created_at == latest.c.latest))
        .where(*visibility(db)).order_by(Trace.created_at.desc())).all()
    for trace in traces:
        if trace.conversation_id:
            if trace.conversation_id not in items:
                items[trace.conversation_id] = {'id': trace.conversation_id, 'title': trace.question[:160], 'has_traces': True}
            else:
                items[trace.conversation_id]['has_traces'] = True
    return list(items.values())

@router.get('')
def overview(conversation_id: str | None = None, status: str | None = None,
             page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
             db: Session = Depends(get_db)):
    conditions = visibility(db)
    if conversation_id:
        conditions.append(Trace.conversation_id == conversation_id)
    if status:
        conditions.append(Trace.status == status)
    total = db.scalar(select(func.count()).select_from(Trace).where(*conditions))
    totals = db.execute(select(func.coalesce(func.sum(Trace.total_tokens), 0).label('total_tokens'),
        func.coalesce(func.sum(Trace.call_count), 0).label('call_count'),
        func.coalesce(func.sum(Trace.unknown_calls), 0).label('unknown_calls')).where(*conditions)).mappings().one()
    records = db.scalars(select(Trace).options(defer(Trace.calls_json), defer(Trace.stages_json),
        defer(Trace.request_json), defer(Trace.answer)).where(*conditions).order_by(Trace.created_at.desc(), Trace.id)
        .offset((page - 1) * page_size).limit(page_size))
    return {'items': [summary(item) for item in records], 'total': total, 'page': page, 'page_size': page_size, 'summary': dict(totals)}

@router.get('/{trace_id}')
def detail(trace_id: str, db: Session = Depends(get_db)):
    item = db.scalar(select(Trace).where(Trace.id == trace_id, *visibility(db)))
    if not item:
        raise HTTPException(404, '监控记录不存在或无权访问')
    return {**summary(item), 'answer': item.answer, 'error': item.error,
            'request': json.loads(item.request_json), 'stages': json.loads(item.stages_json),
            'calls': json.loads(item.calls_json)}


from typing import Literal
from pydantic import BaseModel, Field

class ClientEvent(BaseModel):
    name: Literal['页面发起请求', '收到响应头', '收到首段文本', '流式响应读取完成', '页面渲染完成', '页面输出停止', '页面输出失败']
    elapsed_ms: int = Field(ge=0, le=86_400_000)

class ClientEvents(BaseModel):
    events: list[ClientEvent] = Field(max_length=8)

@router.put('/{trace_id}/client-events')
def client_events(trace_id: str, payload: ClientEvents, db: Session = Depends(get_db)):
    item = db.scalar(select(Trace).where(Trace.id == trace_id, *visibility(db)))
    if not item:
        raise HTTPException(404, '监控记录不存在或无权访问')
    metadata = json.loads(item.request_json)
    metadata['client_events'] = [event.model_dump() for event in payload.events]
    item.request_json = json.dumps(metadata, ensure_ascii=False)
    db.commit()
    return {'ok': True}
