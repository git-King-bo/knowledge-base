from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.config import settings


@dataclass(slots=True)
class EmbeddingConfig:
    api_url: str
    api_key: str | None
    model: str


class EmbeddingClient:
    def __init__(self, config: EmbeddingConfig | None = None) -> None:
        self.config = config or EmbeddingConfig(
            api_url=settings.embedding_api_url,
            api_key=settings.embedding_api_key or None,
            model=settings.embedding_model,
        )

    @property
    def enabled(self) -> bool:
        return bool(self.config.api_url.strip() and self.config.model.strip())

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=self.config.api_url.rstrip("/"), timeout=60.0)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not self.enabled:
            raise RuntimeError("Embedding config is not enabled")
        if not texts:
            return []

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
        return embeddings

    def embed_text(self, text: str) -> list[float]:
        embeddings = self.embed_texts([text])
        return embeddings[0] if embeddings else []
