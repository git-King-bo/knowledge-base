from urllib.parse import urlsplit
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


def infer_provider(base_url: str) -> str:
    """Choose among the supported adapters; no network probe or credential transfer."""
    address=base_url.strip().rstrip('/')
    if address == 'local://mock':
        return 'mock'
    host=(urlsplit(address).hostname or '').lower()
    if host == 'api.openai.com':
        return 'openai'
    if host == 'aliyuncs.com' or host.endswith('.aliyuncs.com'):
        return 'qwen'
    if host == 'api.deepseek.com':
        return 'deepseek'
    return 'openai-compatible'
