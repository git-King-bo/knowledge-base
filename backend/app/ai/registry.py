from app.ai.base import AIProvider
from app.ai.providers.mock import MockProvider
from app.ai.providers.openai_compatible import OpenAICompatibleProvider


class AIProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, AIProvider] = {}
        self._fallback = OpenAICompatibleProvider()
        self.register(MockProvider())
        self.register(self._fallback, aliases=["openai", "deepseek", "qwen", "openai-compatible"])

    def register(self, provider: AIProvider, aliases: list[str] | None = None) -> None:
        names = aliases or [provider.provider_name]
        for name in names:
            self._providers[name] = provider

    def resolve(self, provider_name: str) -> AIProvider:
        return self._providers.get(provider_name, self._fallback)

    def available_provider_types(self) -> list[str]:
        return sorted(self._providers.keys())


ai_provider_registry = AIProviderRegistry()
