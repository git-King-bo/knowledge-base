from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class CategoryModel(Base):
    __tablename__ = "categories"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)


class DocumentModel(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category_id: Mapped[str] = mapped_column(ForeignKey("categories.id"), nullable=False)
    tags: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    updated_at: Mapped[date] = mapped_column(Date, nullable=False)

    category: Mapped[CategoryModel] = relationship()


class AIProviderModel(Base):
    __tablename__ = "ai_providers"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    base_url: Mapped[str] = mapped_column(String(300), nullable=False)
    api_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="")
    api_key_hint: Mapped[str] = mapped_column(String(40), nullable=False, default="未填写")
    default_model: Mapped[str] = mapped_column(String(120), nullable=False)
    enable_thinking: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    models: Mapped[list["AIModelModel"]] = relationship(
        back_populates="provider_config",
        cascade="all, delete-orphan",
    )


class AIModelModel(Base):
    __tablename__ = "ai_models"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    provider_id: Mapped[str] = mapped_column(ForeignKey("ai_providers.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    context_window: Mapped[int] = mapped_column(Integer, nullable=False, default=32000)
    supports_tools: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    supports_vision: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")

    provider_config: Mapped[AIProviderModel] = relationship(back_populates="models")


class KnowledgeSourceModel(Base):
    __tablename__ = "knowledge_sources"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False, default="application/octet-stream")
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="uploaded")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    chunks: Mapped[list["KnowledgeChunkModel"]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
    )


class KnowledgeBaseModel(Base):
    __tablename__ = "knowledge_bases"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    sources: Mapped[list["KnowledgeBaseSourceModel"]] = relationship(
        back_populates="knowledge_base",
        cascade="all, delete-orphan",
    )


class KnowledgeBaseSourceModel(Base):
    __tablename__ = "knowledge_base_sources"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    knowledge_base_id: Mapped[str] = mapped_column(ForeignKey("knowledge_bases.id"), nullable=False)
    source_id: Mapped[str] = mapped_column(ForeignKey("knowledge_sources.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    knowledge_base: Mapped[KnowledgeBaseModel] = relationship(back_populates="sources")
    source: Mapped[KnowledgeSourceModel] = relationship()


class KnowledgeChunkModel(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("knowledge_sources.id"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    vector_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    source: Mapped[KnowledgeSourceModel] = relationship(back_populates="chunks")
    embedding: Mapped["KnowledgeChunkEmbeddingModel | None"] = relationship(
        back_populates="chunk",
        cascade="all, delete-orphan",
        uselist=False,
    )


class KnowledgeChunkEmbeddingModel(Base):
    __tablename__ = "knowledge_chunk_embeddings"

    chunk_id: Mapped[str] = mapped_column(ForeignKey("knowledge_chunks.id"), primary_key=True)
    embedding_model: Mapped[str] = mapped_column(String(120), nullable=False)
    embedding_json: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_dim: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    chunk: Mapped[KnowledgeChunkModel] = relationship(back_populates="embedding")


class AIActivityLogModel(Base):
    __tablename__ = "ai_activity_logs"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    request_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    response_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class TokenUsageModel(Base):
    __tablename__ = "token_usage"

    log_id: Mapped[str] = mapped_column(ForeignKey("ai_activity_logs.id"), primary_key=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cached_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    knowledge_base_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)


class TalentModel(Base):
    """One source spreadsheet row per record; names are not unique identifiers."""

    __tablename__ = "talents"
    __table_args__ = (UniqueConstraint("source_id", "sheet_name", "source_row", name="uq_talent_source_row"),)

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("knowledge_sources.id"), nullable=False, index=True)
    sheet_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_row: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_data_json: Mapped[str] = mapped_column(Text, nullable=False)
    formulas_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    name: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)  # 姓名
    organization: Mapped[str | None] = mapped_column(Text, nullable=True)  # 当前机构
    position: Mapped[str | None] = mapped_column(Text, nullable=True)  # 当前职务
    biography: Mapped[str | None] = mapped_column(Text, nullable=True)  # 详细个人简介
    education: Mapped[str | None] = mapped_column(Text, nullable=True)  # 教育经历
    work_experience: Mapped[str | None] = mapped_column(Text, nullable=True)  # 工作经历
    projects: Mapped[str | None] = mapped_column(Text, nullable=True)  # 创业／项目经历
    achievements: Mapped[str | None] = mapped_column(Text, nullable=True)  # 代表成果
    talent_identity: Mapped[str | None] = mapped_column(Text, nullable=True)  # 人才身份
    industry_direction: Mapped[str | None] = mapped_column(Text, nullable=True)  # 未来产业方向
    keywords: Mapped[str | None] = mapped_column(Text, nullable=True)  # 细分关键词
    public_views: Mapped[str | None] = mapped_column(Text, nullable=True)  # 公开观点
    contact_clues: Mapped[str | None] = mapped_column(Text, nullable=True)  # 公开联系方式线索
    source_links: Mapped[str | None] = mapped_column(Text, nullable=True)  # 来源链接
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # 本次变化摘要
    pending_confirmation: Mapped[str | None] = mapped_column(Text, nullable=True)  # 待人工确认事项
    last_auto_update: Mapped[str | None] = mapped_column(Text, nullable=True)  # 上次自动更新时间
    auto_update_result: Mapped[str | None] = mapped_column(Text, nullable=True)  # 自动更新结果
    operation_records: Mapped[str | None] = mapped_column(Text, nullable=True)  # 关联运营记录
    location: Mapped[str | None] = mapped_column(Text, nullable=True)  # 所在国家／城市
    english_name: Mapped[str | None] = mapped_column(Text, nullable=True)  # 英文名
    technical_role: Mapped[str | None] = mapped_column(Text, nullable=True)  # 技术角色定位
    evidence_links: Mapped[str | None] = mapped_column(Text, nullable=True)  # 证据链接
    scholar_citations: Mapped[str | None] = mapped_column(Text, nullable=True)  # Google Scholar总引用数
    scholar_url: Mapped[str | None] = mapped_column(Text, nullable=True)  # Google Scholar主页
    scholar_h_index: Mapped[str | None] = mapped_column(Text, nullable=True)  # Google Scholar h-index
    academic_updated_at: Mapped[str | None] = mapped_column(Text, nullable=True)  # 学术指标更新时间
    open_source_assets: Mapped[str | None] = mapped_column(Text, nullable=True)  # 开源资产摘要
    openalex_url: Mapped[str | None] = mapped_column(Text, nullable=True)  # OpenAlex主页
    openalex_works: Mapped[str | None] = mapped_column(Text, nullable=True)  # OpenAlex作品数
    openalex_citations: Mapped[str | None] = mapped_column(Text, nullable=True)  # OpenAlex总引用数
    openalex_h_index: Mapped[str | None] = mapped_column(Text, nullable=True)  # OpenAlex h-index
    openalex_updated_at: Mapped[str | None] = mapped_column(Text, nullable=True)  # OpenAlex指标更新时间
    research_document: Mapped[str | None] = mapped_column(Text, nullable=True)  # 深度调研文档
    domain: Mapped[str | None] = mapped_column(Text, nullable=True)  # 领域


class UserModel(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="viewer")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class LoginSessionModel(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class BaseAccessModel(Base):
    __tablename__ = "base_access"
    base_id: Mapped[str] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="viewer")


class AuditModel(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(80), index=True)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    target: Mapped[str] = mapped_column(String(255), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)


class RequestBudgetModel(Base):
    __tablename__ = "request_budgets"
    user_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class SourceIndexModel(Base):
    __tablename__ = "source_indexes"
    source_id: Mapped[str] = mapped_column(ForeignKey("knowledge_sources.id", ondelete="CASCADE"), primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    edited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    indexed_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ImportJobModel(Base):
    __tablename__ = "import_jobs"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("knowledge_sources.id"), index=True)
    base_id: Mapped[str | None] = mapped_column(String(80), index=True)
    user_id: Mapped[str | None] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(40), nullable=False, default="queued")
    completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class TalentRevisionModel(Base):
    __tablename__ = "talent_revisions"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    talent_id: Mapped[str] = mapped_column(ForeignKey("talents.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(String(80))
    data_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ChunkTalentModel(Base):
    __tablename__ = "chunk_talents"
    chunk_id: Mapped[str] = mapped_column(ForeignKey("knowledge_chunks.id", ondelete="CASCADE"), primary_key=True)
    talent_id: Mapped[str] = mapped_column(ForeignKey("talents.id", ondelete="CASCADE"), index=True)


class SavedConversationModel(Base):
    __tablename__ = "saved_conversations"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    messages_json: Mapped[str] = mapped_column(Text, nullable=False)
    favorite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    feedback: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class TrashModel(Base):
    __tablename__ = "trash"
    base_id: Mapped[str] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="CASCADE"), primary_key=True)
    deleted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    previous_status: Mapped[str] = mapped_column(String(20), nullable=False)


class AgentTraceModel(Base):
    __tablename__ = 'agent_traces'

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(80), index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(80), index=True)
    turn_id: Mapped[str | None] = mapped_column(String(80), index=True)
    knowledge_base_id: Mapped[str | None] = mapped_column(String(80), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text, default='')
    status: Mapped[str] = mapped_column(String(20), default='running', index=True)
    error: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    first_token_ms: Mapped[int | None] = mapped_column(Integer)
    request_json: Mapped[str] = mapped_column(Text, default='{}')
    stages_json: Mapped[str] = mapped_column(Text, default='[]')
    calls_json: Mapped[str] = mapped_column(Text, default='[]')
    call_count: Mapped[int] = mapped_column(Integer, default=0)
    unknown_calls: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int | None] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int | None] = mapped_column(Integer, default=0)
    cached_tokens: Mapped[int | None] = mapped_column(Integer, default=0)
