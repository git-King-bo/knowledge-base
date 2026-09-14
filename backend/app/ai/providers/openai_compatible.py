import json

from app.schemas.usage import ChatResult, TokenUsage, StreamChunk

import httpx

from app.ai.base import AIProvider
from app.schemas.ai import ChatMessage, ProviderConfig, ProviderTestResult


class OpenAICompatibleProvider(AIProvider):
    """Chat adapter preserving provider-reported usage for every response."""

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
    ) -> ChatResult:
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
                return ChatResult(content=content, usage=TokenUsage.from_response(data))
            delta = choice.get("delta") or {}
            if delta.get("content"):
                return ChatResult(content=delta["content"], usage=TokenUsage.from_response(data))

        raise RuntimeError("Provider returned no answer content")

    def _async_client(self, config: ProviderConfig) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=config.base_url.rstrip("/"), timeout=60.0)

    async def stream_chat(self, config, messages, model=None, api_key=None):
        payload = {
            "model": model or config.default_model,
            "messages": [message.model_dump() for message in messages],
            "stream": True,
            "stream_options": {"include_usage": True},
            "temperature": 0.2,
        }
        async with self._async_client(config) as client:
            async with client.stream("POST", "/chat/completions",
                                     headers=self._auth_headers(api_key), json=payload) as response:
                response.raise_for_status()
                if "text/event-stream" not in response.headers.get("content-type", "").lower():
                    raise RuntimeError("Provider did not return an event stream")
                fields = []
                size = 0
                async for line in response.aiter_lines():
                    if line == "":
                        if not fields:
                            continue
                        text = "\n".join(fields)
                        fields, size = [], 0
                        if text.strip() == "[DONE]":
                            return
                        data = json.loads(text)
                        if not isinstance(data, dict) or data.get("error"):
                            raise RuntimeError("Provider returned a streaming error")
                        choices = data.get("choices") or []
                        delta = ""
                        if choices:
                            delta = (choices[0].get("delta") or {}).get("content") or ""
                            if not isinstance(delta, str):
                                raise RuntimeError("Invalid text delta from provider")
                        yield StreamChunk(delta=delta,
                            usage=TokenUsage.from_response(data) if isinstance(data.get("usage"), dict) else None)
                    elif line.startswith("data:"):
                        field = line[5:]
                        fields.append(field[1:] if field.startswith(" ") else field)
                        size += len(field)
                        if size > 1_000_000:
                            raise RuntimeError("Provider stream event exceeds size limit")
                raise RuntimeError("Provider stream ended before its completion marker")
