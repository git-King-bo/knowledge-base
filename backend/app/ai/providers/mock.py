from app.ai.base import AIProvider
from app.schemas.usage import ChatResult, TokenUsage, StreamChunk
from app.schemas.ai import ChatMessage, ProviderConfig, ProviderTestResult


class MockProvider(AIProvider):
    provider_name = "mock"

    def test(self, config: ProviderConfig, api_key: str | None = None) -> ProviderTestResult:
        return ProviderTestResult(
            provider_id=config.id,
            ok=True,
            message=f"{config.name} is ready. This is a local mock provider.",
            details={"provider": config.provider},
        )

    def chat(
        self,
        config: ProviderConfig,
        messages: list[ChatMessage],
        model: str | None = None,
        api_key: str | None = None,
    ) -> ChatResult:
        last_user_message = next(
            (message.content for message in reversed(messages) if message.role == "user"),
            "",
        )
        selected_model = model or config.default_model
        return ChatResult(content=f"[{selected_model}] Mock response: {last_user_message or 'No user message provided.'}", usage=TokenUsage(source="mock"))

    async def stream_chat(self, config, messages, model=None, api_key=None):
        result = self.chat(config, messages, model, api_key)
        for index in range(0, len(result.content), 24):
            yield StreamChunk(delta=result.content[index:index + 24])
        yield StreamChunk(usage=result.usage)
