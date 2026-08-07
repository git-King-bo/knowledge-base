from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


SourceStatus = Literal["uploaded", "parsed", "failed"]
KnowledgeBaseStatus = Literal["active", "archived"]
LogAction = Literal["chat", "ask", "test"]


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=800)
    tags: list[str] = Field(default_factory=list)


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=800)
    tags: list[str] | None = None
    status: KnowledgeBaseStatus | None = None


class KnowledgeBase(BaseModel):
    id: str
    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    status: KnowledgeBaseStatus = "active"
    source_count: int = 0
    chunk_count: int = 0
    created_at: datetime
    updated_at: datetime


class KnowledgeSource(BaseModel):
    id: str
    filename: str
    mime_type: str
    status: SourceStatus
    chunk_count: int = 0
    error_message: str | None = None
    created_at: datetime


class KnowledgeChunk(BaseModel):
    id: str
    source_id: str
    chunk_index: int
    title: str | None = None
    content: str
    token_count: int = 0
    score: float | None = None


class KnowledgeSearchResult(BaseModel):
    query: str
    hits: list[KnowledgeChunk]


class UploadResponse(BaseModel):
    source: KnowledgeSource
    chunks: list[KnowledgeChunk]
    knowledge_base: KnowledgeBase | None = None


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=5000)
    knowledge_base_id: str | None = None
    provider_id: str | None = None
    model: str | None = None
    top_k: int = Field(default=5, ge=1, le=12)


class AskResponse(BaseModel):
    answer: str
    provider_id: str
    model: str
    sources: list[KnowledgeChunk]


class AIActivityLog(BaseModel):
    id: str
    action: LogAction
    provider_id: str
    model: str
    success: bool
    latency_ms: int
    request_text: str
    response_text: str
    created_at: datetime
