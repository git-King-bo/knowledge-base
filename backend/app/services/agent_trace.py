"""Observable execution steps, not private model reasoning. Context follows worker threads."""
import asyncio
import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
from time import perf_counter
from uuid import uuid4

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.security import actor
from app.db.models import AgentTraceModel, SavedConversationModel
from app.db.session import get_db
from app.schemas.knowledge import AskRequest

current_trace = ContextVar('agent_trace', default=None)
logger = logging.getLogger(__name__)

def elapsed(trace):
    return round((perf_counter() - trace['started']) * 1000)

@contextmanager
def trace_stage(name):
    trace = current_trace.get()
    if trace is None:
        yield
        return
    entry = {'name': name, 'start_ms': elapsed(trace), 'duration_ms': 0, 'status': 'running'}
    trace['stages'].append(entry)
    previous = trace['phase']
    trace['phase'] = name
    try:
        yield
        entry['status'] = 'success'
    except BaseException as exc:
        # These exceptions carry a successful deterministic answer/clarification.
        entry['status'] = 'success' if type(exc).__name__ in {'PreparedTalentAnswer', 'RetrievalClarification'} else 'error'
        raise
    finally:
        entry['duration_ms'] = elapsed(trace) - entry['start_ms']
        trace['phase'] = previous

def traced(name):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            with trace_stage(name):
                return fn(*args, **kwargs)
        return wrapped
    return decorate

def trace_note(name, *, status="success", **data):
    trace = current_trace.get()
    if trace is not None:
        trace['stages'].append({'name': name, 'start_ms': elapsed(trace), 'duration_ms': 0,
                                'status': status, 'data': data})

def trace_id():
    trace = current_trace.get()
    return trace['id'] if trace else ''

def trace_output(text, *, append=False, status=None, error=''):
    trace = current_trace.get()
    if trace is None:
        return
    if text and trace['first_token_ms'] is None:
        trace['first_token_ms'] = elapsed(trace)
        trace_note('开始输出')
    trace['answer'] = (trace['answer'] + text if append else text)[:200_000]
    if status:
        trace['status'] = status
    if error:
        trace['error'] = error[:2000]

def trace_call(record, usage):
    trace = current_trace.get()
    if trace is not None:
        end = elapsed(trace)
        trace['stages'].append({'name': '模型调用 · ' + record.model,
            'start_ms': max(0, end - record.latency_ms), 'duration_ms': record.latency_ms,
            'status': 'success' if record.success else 'error',
            'data': {'action': record.action, 'call_id': record.id}})
        trace['calls'].append({
            'id': record.id, 'stage': trace['phase'] or ('向量编码' if record.action == 'embedding' else '回答生成'),
            'action': record.action, 'provider_id': record.provider_id, 'model': record.model,
            'success': record.success, 'latency_ms': record.latency_ms,
            'request_text': record.request_text[:100_000], 'response_text': record.response_text[:200_000],
            **usage.model_dump(),
        })

async def capture_trace(payload: AskRequest, db: Session = Depends(get_db)):
    user = actor.get()
    if payload.conversation_id:
        conversation = db.get(SavedConversationModel, payload.conversation_id)
        if conversation and (not user or conversation.user_id != user.id):
            raise HTTPException(404, '会话不存在')
    trace = dict(id=str(uuid4()), started=perf_counter(), phase='', stages=[], calls=[],
                 answer='', status='running', error='', first_token_ms=None)
    metadata = payload.model_dump(exclude={'history', 'continuation'})
    metadata['history_turns'] = len(payload.history)
    metadata['continuation'] = payload.continuation is not None
    record = AgentTraceModel(id=trace['id'], user_id=user.id if user else None,
        conversation_id=payload.conversation_id, turn_id=payload.turn_id,
        knowledge_base_id=payload.knowledge_base_id, question=payload.question,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        request_json=json.dumps(metadata, ensure_ascii=False))
    db.add(record)
    db.commit()
    token = current_trace.set(trace)
    trace_note('接收页面请求', question=payload.question, parameters=metadata, history=[turn.model_dump() for turn in payload.history])
    trace_note('请求校验与访问控制', result='已通过请求字段校验、登录验证、知识库权限和调用预算检查；被拦截的请求不会进入此链路')
    try:
        yield trace
    except asyncio.CancelledError:
        trace['status'] = 'cancelled'
        raise
    except Exception as exc:
        trace['status'] = 'error'
        trace['error'] = str(getattr(exc, 'detail', exc))[:2000]
        raise
    finally:
        if trace['status'] == 'running':
            trace['status'] = 'interrupted'
        trace_note('请求结束', result=trace['status'], output_characters=len(trace['answer']))
        current_trace.reset(token)
        # Do not let a monitoring write hide a completed answer or the original error.
        try:
            db.rollback()
            record = db.get(AgentTraceModel, trace['id'])
            record.answer = trace['answer']
            record.status = trace['status']
            record.error = trace['error']
            record.duration_ms = elapsed(trace)
            record.first_token_ms = trace['first_token_ms']
            record.stages_json = json.dumps(sorted(trace['stages'], key=lambda step: step['start_ms']), ensure_ascii=False)
            record.calls_json = json.dumps(trace['calls'], ensure_ascii=False)
            record.call_count = len(trace['calls'])
            record.unknown_calls = sum(call['total_tokens'] is None for call in trace['calls'])
            record.total_tokens = sum(call['total_tokens'] or 0 for call in trace['calls'])
            for key in ('input_tokens', 'output_tokens', 'cached_tokens'):
                values = [call[key] for call in trace['calls']]
                setattr(record, key, None if any(value is None for value in values) else sum(values))
            db.commit()
        except Exception:
            db.rollback()
            logger.exception('Failed to finalize agent trace %s', trace['id'])
