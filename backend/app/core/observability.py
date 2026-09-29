import json
import logging
from time import perf_counter
from uuid import uuid4
from fastapi import Request
from starlette.responses import JSONResponse

log=logging.getLogger('knowledge.http')
log.setLevel(logging.INFO)
if not log.handlers:
    log.addHandler(logging.StreamHandler())
log.propagate=False
counts={'requests':0,'errors':0}

async def observe(request:Request,call_next):
    request_id=str(uuid4());start=perf_counter()
    try:
        response=await call_next(request)
    except Exception:
        log.exception('unhandled request_id=%s',request_id)
        response=JSONResponse({'detail':'服务内部错误，请联系管理员','request_id':request_id},status_code=500)
    counts['requests']+=1
    if response.status_code>=500:counts['errors']+=1
    response.headers['X-Request-ID']=request_id
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='same-origin'
    log.info(json.dumps({'request_id':request_id,'method':request.method,'route':getattr(request.scope.get('route'),'path',request.url.path),
                        'status':response.status_code,'headers_ms':round((perf_counter()-start)*1000)},ensure_ascii=False))
    return response
