"""Optional bounded rerank transport; failure preserves the fused candidate order.

Configured URL is the complete endpoint. Request: model, query, documents, top_n.
Response: results[{index,relevance_score}], with indexes relative to documents.
"""
import json
import math
from time import perf_counter
import httpx
from app.core.config import settings
from app.core.security import validate_provider_url
from app.core.limits import claim_model_input
from app.repositories.sqlite import AIRepository
from app.schemas.ai import ChatMessage
from app.schemas.usage import TokenUsage
from app.services.agent_trace import trace_note


def rerank(query, documents, db=None, base_id=None):
    if not settings.rerank_api_url or not settings.rerank_model or not documents:
        return list(range(len(documents))), 'not_configured'
    started=perf_counter();usage=TokenUsage();success=False
    # At most 60 short candidates; don't send whole biographies to a ranker.
    snippets=[text[:800] for text in documents[:60]]
    try:
        validate_provider_url(settings.rerank_api_url,resolve=True)
        claim_model_input([ChatMessage(role='user',content=query+'\n'+'\n'.join(snippets))])
    except Exception:
        return list(range(len(documents))), 'unavailable'
    try:
        with httpx.Client(timeout=httpx.Timeout(settings.rerank_timeout),trust_env=False) as client:
            response=client.post(settings.rerank_api_url,headers={
                'Authorization':'Bearer '+settings.rerank_api_key},json={
                'model':settings.rerank_model,'query':query,'documents':snippets,'top_n':len(snippets)})
            response.raise_for_status();data=response.json()
        results=data['results']
        indexes=[r['index'] for r in results]
        if (len(indexes)!=len(snippets) or len(set(indexes))!=len(indexes)
                or any(type(i) is not int or i<0 or i>=len(snippets) for i in indexes)
                or any(not math.isfinite(float(r['relevance_score'])) for r in results)):
            raise ValueError('Invalid rerank response')
        indexes=[r['index'] for r in sorted(results,key=lambda r:float(r['relevance_score']),reverse=True)]
        usage=TokenUsage.from_response(data);success=True
        return indexes+list(range(len(snippets),len(documents))), 'ready'
    except Exception as exc:
        trace_note('重排降级',status='fallback',error_type=type(exc).__name__)
        return list(range(len(documents))), 'unavailable'
    finally:
        if db is not None:
            AIRepository(db).create_activity_log(action='ask',provider_id='rerank',model=settings.rerank_model,
                request_text=f'Rerank {len(snippets)} candidates',response_text='',success=success,
                latency_ms=round((perf_counter()-started)*1000),usage=usage,knowledge_base_id=base_id)
