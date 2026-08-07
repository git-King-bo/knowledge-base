from urllib.parse import urljoin

import httpx

from app.ai.base import AIProvider
from app.schemas.ai import ChatMessage, ProviderConfig, ProviderTestResult


class OpenAICompatibleProvider(AIProvider):
    """Placeholder for OpenAI-compatible chat APIs.

    DeepSeek, Qwen and OpenAI-compatible gateways can share this adapter once
    credentials and HTTP client wiring are added.
    """

    provider_name = "openai-compatible"

    def _auth_headers(self, api_key: str | None) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def _client(self, config: ProviderConfig) -> httpx.Client:
        return httpx.Client(base_url=config.base_url.rstrip("/"), timeout=60.0)

    def test(self, config: ProviderConfig, api_key: str | None = None) -> ProviderTestResult:
        try:
            with self._client(config) as client:
                response = client.get("/models", headers=self._auth_headers(api_key))
                response.raise_for_status()
        except Exception as exc:  # pragma: no cover - surfaced in API response
            return ProviderTestResult(
                provider_id=config.id,
                ok=False,
                message=f"Provider test failed: {exc}",
            )

        return ProviderTestResult(
            provider_id=config.id,
            ok=True,
            message="Provider reachable and models endpoint responded successfully.",
            details={"base_url": config.base_url, "provider": config.provider},
        )

    def chat(
        self,
        config: ProviderConfig,
        messages: list[ChatMessage],
        model: str | None = None,
        api_key: str | None = None,
    ) -> str:
        selected_model = model or config.default_model
        payload = {
            "model": selected_model,
            "messages": [message.model_dump() for message in messages],
            "stream": False,
            "temperature": 0.2,
        }

        with self._client(config) as client:
            response = client.post(
                "/chat/completions",
                headers=self._auth_headers(api_key),
                json=payload,
            )
            response.raise_for_status()

        data = response.json()
        choices = data.get("choices") or []
        if choices:
            choice = choices[0]
            message = choice.get("message") or {}
            content = message.get("content")
            if content:
                return content
            delta = choice.get("delta") or {}
            if delta.get("content"):
                return delta["content"]

        return str(data)
