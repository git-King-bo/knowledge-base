"""Single-process inference concurrency and persistent per-user daily budgets."""
import asyncio
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.security import authenticate, now, usage_counter
from app.db.session import get_db
from app.db.models import RequestBudgetModel

def ensure_budget(db, user_id, day):
    values = dict(user_id=user_id, day=day, requests=0, tokens=0, reserved=0)
    if db.get_bind().dialect.name == 'mysql':
        statement = mysql_insert(RequestBudgetModel).values(**values)
        # 重复时保持计数不变；不能用 REPLACE，否则会重置预算。
        statement = statement.on_duplicate_key_update(user_id=statement.inserted.user_id)
    else:
        statement = sqlite_insert(RequestBudgetModel).values(**values).on_conflict_do_nothing()
    db.execute(statement)


_active=0

async def inference_budget(request:Request,db:Session=Depends(get_db),user=Depends(authenticate)):
    global _active
    path=request.url.path
    inference=path.endswith(('/ask','/ask/stream','/chat','/search','/test'))
    if not user or not inference:
        yield
        return
    if _active>=settings.model_concurrency:
        raise HTTPException(429,'模型并发已满，请稍后重试',headers={'Retry-After':'5'})
    day=now().date().isoformat()
    # Each dispatch tops up this initial reservation to its actual input/output bound.
    reserve=4096 + settings.model_max_output_tokens
    ensure_budget(db, user.id, day)
    result=db.execute(update(RequestBudgetModel).where(RequestBudgetModel.user_id==user.id,RequestBudgetModel.day==day,
        RequestBudgetModel.requests<settings.model_requests_per_day,
        RequestBudgetModel.tokens+RequestBudgetModel.reserved+reserve<=settings.daily_token_budget).values(
        requests=RequestBudgetModel.requests+1,reserved=RequestBudgetModel.reserved+reserve))
    db.commit()
    if result.rowcount!=1:
        budget=db.get(RequestBudgetModel,(user.id,day))
        if budget.requests>=settings.model_requests_per_day:
            raise HTTPException(429,f'系统今日调用次数已达上限（{budget.requests}/{settings.model_requests_per_day}）')
        raise HTTPException(429,f'系统今日Token预算不足：已计入{budget.tokens}，预留{budget.reserved}，上限{settings.daily_token_budget}；非模型服务商余额提示')
    _active+=1
    counter={'tokens':0,'calls':0,'unknown':False,'unknown_tokens':0,'pending':[],
             'budget_db':db,'user_id':user.id,'day':day,'reservation':reserve}
    context=usage_counter.set(counter)
    try:
        yield
    finally:
        _active-=1
        usage_counter.reset(context)
        db.rollback()
        charged=counter['tokens'] + counter['unknown_tokens'] + sum(counter['pending'])
        db.execute(update(RequestBudgetModel).where(RequestBudgetModel.user_id==user.id,RequestBudgetModel.day==day).values(
            reserved=RequestBudgetModel.reserved-counter['reservation'],tokens=RequestBudgetModel.tokens+charged))
        db.commit()


def claim_token_reservation(estimate):
    """Reserve dispatched work, retaining its bound when no usage is returned."""
    counter=usage_counter.get()
    if counter is None or 'pending' not in counter:
        return
    required=counter['tokens']+counter['unknown_tokens']+sum(counter['pending'])+estimate
    extra=max(0,required-counter['reservation'])
    if extra:
        db=counter['budget_db']
        result=db.execute(update(RequestBudgetModel).where(
            RequestBudgetModel.user_id==counter['user_id'],RequestBudgetModel.day==counter['day'],
            RequestBudgetModel.tokens+RequestBudgetModel.reserved+extra<=settings.daily_token_budget
        ).values(reserved=RequestBudgetModel.reserved+extra))
        db.commit()
        if result.rowcount!=1:
            raise HTTPException(429,'系统剩余Token预算不足以处理本次输入，请缩短上下文或调整每日预算')
        counter['reservation']+=extra
    counter['pending'].append(estimate)


def claim_model_input(messages):
    counter=usage_counter.get()
    characters=sum(len(m.content) for m in messages)
    if characters>60000:raise ValueError('上下文超过60000字符，请缩小范围')
    if counter is not None:
        dispatched=counter.get('dispatched',0)
        if dispatched>=4:raise ValueError('单次操作模型调用次数已达上限，请缩小查询范围')
        estimate=sum(len(m.content.encode('utf-8'))+32 for m in messages)+settings.model_max_output_tokens
        claim_token_reservation(estimate)
        counter['dispatched']=dispatched+1


def embed_with_budget(db,job,client,texts):
    if not job.user_id:return client.embed_texts(texts)
    from app.core.security import usage_counter
    day=now().date().isoformat();reserve=sum(len(text) for text in texts)*4
    ensure_budget(db, job.user_id, day)
    result=db.execute(update(RequestBudgetModel).where(RequestBudgetModel.user_id==job.user_id,RequestBudgetModel.day==day,
        RequestBudgetModel.tokens+RequestBudgetModel.reserved+reserve<=settings.daily_token_budget).values(reserved=RequestBudgetModel.reserved+reserve))
    db.commit()
    if result.rowcount!=1:raise ValueError('今日Token预算不足，明日可重试，已完成批次保留')
    counter={'tokens':0,'calls':0,'unknown':False};context=usage_counter.set(counter)
    try:return client.embed_texts(texts)
    finally:
        usage_counter.reset(context)
        # If the network outcome is unknown, retain a conservative charge.
        charge=reserve if counter['unknown'] or not counter['calls'] else counter['tokens']
        db.execute(update(RequestBudgetModel).where(RequestBudgetModel.user_id==job.user_id,RequestBudgetModel.day==day).values(
            reserved=RequestBudgetModel.reserved-reserve,tokens=RequestBudgetModel.tokens+charge));db.commit()
