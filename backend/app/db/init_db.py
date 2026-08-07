from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import AIModelModel, AIProviderModel, CategoryModel, DocumentModel
from app.db.session import Base, engine


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def seed_db(db: Session) -> None:
    has_categories = db.scalar(select(CategoryModel).limit(1))
    if not has_categories:
        db.add_all(
            [
                CategoryModel(id="product", name="产品知识"),
                CategoryModel(id="engineering", name="研发规范"),
                CategoryModel(id="operations", name="运营手册"),
            ]
        )

    has_documents = db.scalar(select(DocumentModel).limit(1))
    if not has_documents:
        db.add_all(
            [
                DocumentModel(
                    id="doc-product-overview",
                    title="知识库 MVP 范围",
                    summary="第一版先打通文档增删改查、搜索、分类、标签和模型配置。",
                    content="# 知识库 MVP 范围\n\n- 文档 CRUD\n- Markdown 预览\n- 模型配置",
                    category_id="product",
                    tags="mvp,planning",
                    status="published",
                    updated_at=date.today(),
                ),
                DocumentModel(
                    id="doc-ai-provider",
                    title="模型 Provider 接入约定",
                    summary="模型 API 不进入业务层，通过 provider adapter 和 registry 做统一切换。",
                    content="# 模型 Provider 接入约定\n\n新增模型时只补 adapter 和配置。",
                    category_id="engineering",
                    tags="ai,provider",
                    status="draft",
                    updated_at=date.today(),
                ),
            ]
        )

    if settings.default_api_url:
        for item in db.scalars(select(AIProviderModel)).all():
            item.is_default = False
        agent_provider = db.get(AIProviderModel, "provider-agent-default")
        if agent_provider:
            agent_provider.base_url = settings.default_api_url
            agent_provider.api_key_encrypted = ""
            agent_provider.api_key_hint = "已填写" if settings.default_api_key else "未填写"
            agent_provider.default_model = settings.default_api_model
            agent_provider.is_default = True
        else:
            db.add(
                AIProviderModel(
                    id="provider-agent-default",
                    name="Agent Default",
                    provider="openai-compatible",
                    base_url=settings.default_api_url,
                    api_key_encrypted="",
                    api_key_hint="已填写" if settings.default_api_key else "未填写",
                    default_model=settings.default_api_model,
                    is_default=True,
                )
            )

    if not db.get(AIProviderModel, "provider-mock"):
        db.add(
            AIProviderModel(
                id="provider-mock",
                name="Mock Provider",
                provider="mock",
                base_url="local://mock",
                api_key_hint="无需密钥",
                default_model="mock-chat",
                is_default=not bool(settings.default_api_url),
            )
        )

    if not db.get(AIProviderModel, "provider-openai"):
        db.add(
            AIProviderModel(
                id="provider-openai",
                name="OpenAI",
                provider="openai",
                base_url="https://api.openai.com/v1",
                api_key_hint="未填写",
                default_model="gpt-4.1-mini",
                is_default=False,
            )
        )

    if settings.default_api_url:
        agent_model = db.get(AIModelModel, "model-agent-default")
        if agent_model:
            agent_model.name = settings.default_api_model
        else:
            db.add(
                AIModelModel(
                    id="model-agent-default",
                    provider_id="provider-agent-default",
                    name=settings.default_api_model,
                    context_window=128000,
                    supports_tools=True,
                    supports_vision=False,
                    status="ready",
                )
            )

    if not db.get(AIModelModel, "model-mock-chat"):
        db.add(
            AIModelModel(
                id="model-mock-chat",
                provider_id="provider-mock",
                name="mock-chat",
                context_window=32000,
                supports_tools=True,
                supports_vision=False,
                status="ready",
            )
        )

    if not db.get(AIModelModel, "model-gpt-4-1-mini"):
        db.add(
            AIModelModel(
                id="model-gpt-4-1-mini",
                provider_id="provider-openai",
                name="gpt-4.1-mini",
                context_window=1000000,
                supports_tools=True,
                supports_vision=True,
                status="draft",
            )
        )

    db.commit()
