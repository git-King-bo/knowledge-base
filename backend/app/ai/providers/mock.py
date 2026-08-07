from app.ai.base import AIProvider
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
    ) -> str:
        last_user_message = next(
            (message.content for message in reversed(messages) if message.role == "user"),
            "",
        )
        selected_model = model or config.default_model
        return f"[{selected_model}] Mock response: {last_user_message or 'No user message provided.'}"
