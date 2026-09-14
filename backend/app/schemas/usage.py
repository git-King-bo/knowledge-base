from pydantic import BaseModel, Field
from typing import Literal


class TokenUsage(BaseModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    cached_tokens: int | None = Field(default=None, ge=0)
    source: Literal['reported', 'unknown', 'mock'] = 'unknown'

    @classmethod
    def from_response(cls, data: dict, *, embedding: bool = False) -> 'TokenUsage':
        raw = data.get('usage') or {}
        def count(value):
            return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
        incoming = count(raw.get('prompt_tokens', raw.get('input_tokens')))
        outgoing = 0 if embedding else count(raw.get('completion_tokens', raw.get('output_tokens')))
        total = count(raw.get('total_tokens'))
        if total is None and incoming is not None and outgoing is not None:
            total = incoming + outgoing
        details = raw.get('prompt_tokens_details') or raw.get('input_tokens_details') or {}
        cached = count(details.get('cached_tokens'))
        return cls(input_tokens=incoming, output_tokens=outgoing, total_tokens=total,
                   cached_tokens=cached, source='reported' if total is not None else 'unknown')


class ChatResult(BaseModel):
    content: str
    usage: TokenUsage = Field(default_factory=TokenUsage)


class StreamChunk(BaseModel):
    delta: str = ""
    usage: TokenUsage | None = None
