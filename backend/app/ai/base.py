from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from app.schemas.usage import ChatResult, StreamChunk

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
    ) -> ChatResult:
        raise NotImplementedError

    @abstractmethod
    def stream_chat(
        self, config: ProviderConfig, messages: list[ChatMessage],
        model: str | None = None, api_key: str | None = None,
    ) -> AsyncIterator[StreamChunk]:
        raise NotImplementedError
