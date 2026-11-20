from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter, sleep
from sqlalchemy.orm import Session
from app.repositories.sqlite import AIRepository
from app.schemas.usage import TokenUsage

import httpx
import json
import hashlib
import math
import threading
from collections import OrderedDict
from time import monotonic
from contextvars import ContextVar

from app.core.config import settings
from app.core.security import validate_provider_url

_query_mode = ContextVar('embedding_query_mode', default=False)
_circuits = OrderedDict()
_circuit_lock = threading.Lock()
_query_slots=threading.BoundedSemaphore(2)


@dataclass(slots=True)
class EmbeddingConfig:
    api_url: str
    api_key: str | None
    model: str
    query_timeout: float | None = None


class EmbeddingClient:
    def __init__(self, config: EmbeddingConfig | None = None, *, db: Session | None = None, knowledge_base_id: str | None = None) -> None:
        self.db = db
        self.knowledge_base_id = knowledge_base_id
        self.config = config or EmbeddingConfig(
            api_url=settings.embedding_api_url,
            api_key=settings.embedding_api_key or None,
            model=settings.embedding_model,
        )

    @property
    def enabled(self) -> bool:
        return bool(self.config.api_url.strip() and self.config.model.strip())

    def _client(self) -> httpx.Client:
        validate_provider_url(self.config.api_url, resolve=True)
        timeout = (self.config.query_timeout or settings.embedding_query_timeout) if _query_mode.get() else 60.0
        return httpx.Client(base_url=self.config.api_url.rstrip("/"), timeout=httpx.Timeout(timeout, connect=min(2.0, timeout)), trust_env=False)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        retries = 0 if _query_mode.get() else settings.embedding_max_retries
        for attempt in range(retries + 1):
            try:
                return self._embed_once(texts)
            except Exception as exc:
                cause = exc.__cause__ or exc
                transient = isinstance(cause, (httpx.TimeoutException, httpx.NetworkError)) or (
                    isinstance(cause, httpx.HTTPStatusError)
                    and cause.response.status_code in {408, 429, 500, 502, 503, 504}
                )
                if not transient or attempt == retries:
                    raise
                sleep(settings.embedding_retry_backoff_seconds * (2 ** attempt))

    def _embed_once(self, texts: list[str]) -> list[list[float]]:
        started = perf_counter()
        usage = TokenUsage()
        try:
            vectors, usage = self._embed_texts(texts)
        except Exception:
            self._record_usage(usage, False, started, texts)
            raise
        self._record_usage(usage, True, started, texts, vectors)
        return vectors

    def _record_usage(self, usage: TokenUsage, success: bool, started: float, texts: list[str], vectors=None):
        from app.services.agent_trace import current_trace
        traced = current_trace.get() is not None
        if self.db is not None:
            AIRepository(self.db).create_activity_log(
                action="embedding", provider_id="embedding", model=self.config.model,
                request_text=json.dumps({"model": self.config.model, "input": texts}, ensure_ascii=False) if traced else f"Embedding batch: {len(texts)} texts",
                response_text=json.dumps({'count':len(vectors),'dimensions':len(vectors[0]) if vectors else 0}) if vectors is not None else '',
                success=success, latency_ms=int((perf_counter() - started) * 1000),
                usage=usage, knowledge_base_id=self.knowledge_base_id,
            )

    def _embed_texts(self, texts: list[str]) -> tuple[list[list[float]], TokenUsage]:
        if not self.enabled:
            raise RuntimeError("Embedding config is not enabled")
        from app.core.limits import claim_token_reservation
        claim_token_reservation(sum(len(text.encode("utf-8")) + 32 for text in texts))
        payload = {
            "model": self.config.model,
            "input": texts,
        }
        with self._client() as client:
            response = client.post("/embeddings", headers=self._headers(), json=payload)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                body = exc.response.text.strip()
                if len(body) > 500:
                    body = f"{body[:500]}..."
                message = f"{exc.response.status_code} {exc.response.reason_phrase} for {exc.request.url}"
                if body:
                    message = f"{message}: {body}"
                raise RuntimeError(message) from exc

        data = response.json()
        items=data.get('data') or []
        indexes=[item.get('index') for item in items]
        if len(items)!=len(texts) or any(type(i) is not int for i in indexes) or sorted(indexes)!=list(range(len(texts))):
            raise RuntimeError('Embedding response indexes do not match the input batch')
        items = sorted(items,key=lambda item:item['index'])
        embeddings: list[list[float]] = []
        for item in items:
            vector = item.get("embedding") or []
            embeddings.append([float(value) for value in vector])
        if len(embeddings) != len(texts):
            raise RuntimeError("Embedding response length mismatch")
        dimensions={len(v) for v in embeddings}
        if len(dimensions)!=1 or not next(iter(dimensions),0) or any(not all(math.isfinite(x) for x in v) or sum(x*x for x in v)<=0 for v in embeddings):
            raise RuntimeError('Embedding response contains invalid vectors')
        if (settings.embedding_dimensions and self.config.model == settings.embedding_model
                and self.config.api_url == settings.embedding_api_url
                and any(len(vector) != settings.embedding_dimensions for vector in embeddings)):
            raise RuntimeError('Embedding dimensions do not match configured model')
        return embeddings, TokenUsage.from_response(data, embedding=True)

    def embed_text(self, text: str) -> list[float]:
        from app.services.query_cache import query_vector_cache
        from app.services.agent_trace import trace_note
        # Key rotation/model changes get an independent circuit. No secrets in logs.
        revision=settings.embedding_revision if self.config.api_url==settings.embedding_api_url and self.config.model==settings.embedding_model else ''
        identity = hashlib.sha256(json.dumps([self.config.api_url,self.config.model,self.config.api_key,revision]).encode()).digest()
        key = (identity, hashlib.sha256(text.encode()).digest())
        cached = query_vector_cache.get(key)
        if cached is not None:
            trace_note('查询向量缓存', hit=True)
            return cached
        with _circuit_lock:
            if _circuits.get(identity, 0) > monotonic():
                trace_note('查询向量熔断', status='fallback', reason='冷却期内直接使用文本检索')
                raise RuntimeError('Embedding query temporarily unavailable (circuit open)')
        # An in-flight successful request is not a failed provider. Bound actual
        # query work without opening a circuit for unrelated concurrent users.
        if not _query_slots.acquire(blocking=False):
            raise RuntimeError('Embedding query concurrency limit reached')
        token = _query_mode.set(True)
        try:
            embeddings = self.embed_texts([text])
            vector = embeddings[0] if embeddings else []
            import math
            if not vector or not all(math.isfinite(v) for v in vector) or sum(v*v for v in vector)<=0:
                raise ValueError('Invalid query embedding')
            query_vector_cache.put(key, vector)
        except Exception as exc:
            cause = exc.__cause__ if isinstance(exc.__cause__, httpx.HTTPStatusError) else exc
            denied = isinstance(cause, httpx.HTTPStatusError) and cause.response.status_code in {401,402,403}
            cooldown = settings.embedding_denied_cooldown if denied else settings.embedding_failure_cooldown
            with _circuit_lock:
                _circuits[identity] = monotonic()+cooldown
                _circuits.move_to_end(identity)
                while len(_circuits)>128:_circuits.popitem(last=False)
            raise
        else:
            with _circuit_lock:
                _circuits.pop(identity,None)
            return vector
        finally:
            _query_mode.reset(token)
            _query_slots.release()
