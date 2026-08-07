from abc import ABC, abstractmethod

from app.schemas.ai import ChatMessage, ProviderConfig, ProviderTestResult


class AIProvider(ABC):
    provider_name: str

    @abstractmethod
    def test(self, config: ProviderConfig, api_key: str | None = None) -> ProviderTestResult:
        raise NotImplementedError

    @abstractmethod
    def chat(
        self,
        config: ProviderConfig,
        messages: list[ChatMessage],
        model: str | None = None,
        api_key: str | None = None,
    ) -> str:
        raise NotImplementedError
