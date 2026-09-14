from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import AIModelModel, AIProviderModel
from app.db.session import Base, engine


def init_db() -> None:
    # Additive initialization keeps existing knowledge, providers and legacy logs.
    Base.metadata.create_all(bind=engine)


def seed_db(db: Session) -> None:
    """Bootstrap local/environment providers once, preserving edits and defaults."""
    has_default = db.scalar(select(AIProviderModel.id).where(AIProviderModel.is_default.is_(True))) is not None
    if settings.default_api_url and not db.get(AIProviderModel, 'provider-agent-default'):
        db.add(AIProviderModel(
            id='provider-agent-default', name='Agent Default', provider='openai-compatible',
            base_url=settings.default_api_url, api_key_encrypted='',
            api_key_hint='已填写' if settings.default_api_key else '未填写',
            default_model=settings.default_api_model, is_default=not has_default,
        ))
        has_default = True
    if not db.get(AIProviderModel, 'provider-mock'):
        db.add(AIProviderModel(
            id='provider-mock', name='Mock Provider', provider='mock', base_url='local://mock',
            api_key_hint='无需密钥', default_model='mock-chat', is_default=not has_default,
        ))
    db.flush()
    for provider_id, model_id in [('provider-agent-default', 'model-agent-default'),
                                   ('provider-mock', 'model-mock-chat')]:
        provider = db.get(AIProviderModel, provider_id)
        if provider and not db.get(AIModelModel, model_id):
            db.add(AIModelModel(id=model_id, provider_id=provider_id, name=provider.default_model,
                               context_window=32000, supports_tools=False, supports_vision=False,
                               status='ready'))
    db.commit()
