from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter, sleep
from sqlalchemy.orm import Session
from app.repositories.sqlite import AIRepository
from app.schemas.usage import TokenUsage

import httpx
import json
import hashlib
import threading
from collections import OrderedDict
from time import monotonic
from contextvars import ContextVar

from app.core.config import settings
from app.core.security import validate_provider_url

_query_mode = ContextVar('embedding_query_mode', default=False)
_circuits = OrderedDict()
_circuit_lock = threading.Lock()


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
                response_text=json.dumps({"vectors": vectors}, ensure_ascii=False) if traced and vectors is not None else "",
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
        items = sorted(data.get("data") or [], key=lambda item: item.get("index", 0))
        embeddings: list[list[float]] = []
        for item in items:
            vector = item.get("embedding") or []
            embeddings.append([float(value) for value in vector])
        if len(embeddings) != len(texts):
            raise RuntimeError("Embedding response length mismatch")
        return embeddings, TokenUsage.from_response(data, embedding=True)

    def embed_text(self, text: str) -> list[float]:
        from app.services.query_cache import query_vector_cache
        from app.services.agent_trace import trace_note
        # Key rotation/model changes get an independent circuit. No secrets in logs.
        identity = hashlib.sha256(json.dumps([self.config.api_url,self.config.model,self.config.api_key]).encode()).digest()
        key = (identity, hashlib.sha256(text.encode()).digest())
        cached = query_vector_cache.get(key)
        if cached is not None:
            trace_note('查询向量缓存', hit=True)
            return cached
        with _circuit_lock:
            if _circuits.get(identity, 0) > monotonic():
                trace_note('查询向量熔断', status='fallback', reason='冷却期内直接使用文本检索')
                raise RuntimeError('Embedding query temporarily unavailable (circuit open)')
            # One probe per provider per process; concurrent queries degrade immediately.
            _circuits[identity] = monotonic()+settings.embedding_query_timeout*5
            _circuits.move_to_end(identity)
            while len(_circuits)>128:
                _circuits.popitem(last=False)
        token = _query_mode.set(True)
        try:
            embeddings = self.embed_texts([text])
            vector = embeddings[0] if embeddings else []
            import math
            if not vector or not all(math.isfinite(v) for v in vector):
                raise ValueError('Invalid query embedding')
            query_vector_cache.put(key, vector)
        except Exception as exc:
            cause = exc.__cause__ if isinstance(exc.__cause__, httpx.HTTPStatusError) else exc
            denied = isinstance(cause, httpx.HTTPStatusError) and cause.response.status_code in {401,402,403}
            cooldown = settings.embedding_denied_cooldown if denied else settings.embedding_failure_cooldown
            with _circuit_lock:
                _circuits[identity] = monotonic()+cooldown
            raise
        else:
            with _circuit_lock:
                _circuits.pop(identity,None)
            return vector
        finally:
            _query_mode.reset(token)
