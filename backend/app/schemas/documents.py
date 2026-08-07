from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


DocumentStatus = Literal["draft", "published"]


class Category(BaseModel):
    id: str
    name: str
    count: int = 0


class DocumentBase(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(default="", max_length=500)
    content: str = ""
    category_id: str
    tags: list[str] = Field(default_factory=list)
    status: DocumentStatus = "draft"


class DocumentCreate(DocumentBase):
    pass


class DocumentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    summary: str | None = Field(default=None, max_length=500)
    content: str | None = None
    category_id: str | None = None
    tags: list[str] | None = None
    status: DocumentStatus | None = None


class Document(DocumentBase):
    id: str
    updated_at: date
