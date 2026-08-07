from typing import Literal

from pydantic import BaseModel, Field, SecretStr


ModelStatus = Literal["ready", "draft", "disabled"]


class ProviderConfigBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    provider: str = Field(min_length=1, max_length=40)
    base_url: str = Field(min_length=1, max_length=300)
    default_model: str = Field(min_length=1, max_length=120)


class ProviderCreate(ProviderConfigBase):
    api_key: SecretStr | None = None


class ProviderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    provider: str | None = Field(default=None, min_length=1, max_length=40)
    base_url: str | None = Field(default=None, min_length=1, max_length=300)
    default_model: str | None = Field(default=None, min_length=1, max_length=120)
    api_key: SecretStr | None = None
    is_default: bool | None = None


class ProviderConfig(ProviderConfigBase):
    id: str
    api_key_hint: str
    is_default: bool


class ProviderModelBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    context_window: int = Field(default=32000, ge=1)
    supports_tools: bool = False
    supports_vision: bool = False
    status: ModelStatus = "draft"


class ProviderModelCreate(ProviderModelBase):
    pass


class ProviderModel(ProviderModelBase):
    id: str
    provider_id: str


class ProviderTestResult(BaseModel):
    provider_id: str
    ok: bool
    message: str
    details: dict[str, str] | None = None


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    provider_id: str | None = None
    model: str | None = None


class ChatResponse(BaseModel):
    provider_id: str
    model: str
    content: str
