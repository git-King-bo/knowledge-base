from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.schemas.knowledge import WebSource


@dataclass(slots=True)
class WebSearchConfig:
    enabled: bool
    provider: str
    api_key: str
    max_results: int
    timeout_seconds: float


class WebSearchClient:
    def __init__(self, config: WebSearchConfig | None = None) -> None:
        self.config = config or WebSearchConfig(
            enabled=settings.web_search_enabled,
            provider=settings.web_search_provider,
            api_key=settings.web_search_api_key,
            max_results=settings.web_search_max_results,
            timeout_seconds=settings.web_search_timeout_seconds,
        )

    @property
    def enabled(self) -> bool:
        return bool(self.config.enabled and self.config.api_key.strip())

    def search(self, query: str) -> list[WebSource]:
        if not self.enabled or not query.strip():
            return []

        provider = self.config.provider.strip().lower()
        if provider == "brave":
            return self._search_brave(query)
        return self._search_tavily(query)

    def _search_tavily(self, query: str) -> list[WebSource]:
        payload = {
            "api_key": self.config.api_key,
            "query": query,
            "max_results": self.config.max_results,
            "include_answer": False,
            "include_raw_content": False,
        }
        with httpx.Client(timeout=self.config.timeout_seconds, trust_env=False) as client:
            response = client.post("https://api.tavily.com/search", json=payload)
            response.raise_for_status()
        data = response.json()
        return [
            WebSource(
                index=index,
                title=str(item.get("title") or item.get("url") or f"Web {index}"),
                url=str(item.get("url") or ""),
                snippet=str(item.get("content") or item.get("snippet") or ""),
                provider="tavily",
            )
            for index, item in enumerate(data.get("results") or [], start=1)
            if item.get("url")
        ]

    def _search_brave(self, query: str) -> list[WebSource]:
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": self.config.api_key,
        }
        params = {
            "q": query,
            "count": self.config.max_results,
        }
        with httpx.Client(timeout=self.config.timeout_seconds, trust_env=False) as client:
            response = client.get("https://api.search.brave.com/res/v1/web/search", headers=headers, params=params)
            response.raise_for_status()
        data = response.json()
        results = (data.get("web") or {}).get("results") or []
        return [
            WebSource(
                index=index,
                title=str(item.get("title") or item.get("url") or f"Web {index}"),
                url=str(item.get("url") or ""),
                snippet=str(item.get("description") or ""),
                provider="brave",
            )
            for index, item in enumerate(results, start=1)
            if item.get("url")
        ]
