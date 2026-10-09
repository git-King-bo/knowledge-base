from abc import ABC, abstractmethod
from contextvars import ContextVar
from collections.abc import AsyncIterator
from app.schemas.usage import ChatResult, StreamChunk

from app.schemas.ai import ChatMessage, ProviderConfig, ProviderTestResult

# 仅结构化规划/核验调用启用，不改变普通聊天和流式回答协议。
json_output_requested = ContextVar('json_output_requested', default=False)


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
