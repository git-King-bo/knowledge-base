from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import AIModelModel, AIProviderModel
from app.db.session import Base, engine


def init_db() -> None:
    # Production upgrades are explicit migrations, never an implicit create_all upgrade.
    if settings.app_env == 'production':
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import inspect, text
        from pathlib import Path
        tables = inspect(engine).get_table_names()
        if tables:
            with engine.connect() as conn:
                stamped = 'alembic_version' in tables and conn.execute(text('SELECT version_num FROM alembic_version')).first()
            if not stamped:
                raise RuntimeError('Existing database has no migration version. Back up and run scripts/prepare_production.py before production startup.')
        config = Config(str(Path(__file__).resolve().parents[2] / 'alembic.ini'))
        config.set_main_option('script_location', str(Path(__file__).resolve().parents[2] / 'alembic'))
        command.upgrade(config, 'head')
    else:
        Base.metadata.create_all(bind=engine)
        # create_all does not add columns to an existing local database.
        from sqlalchemy import inspect, text
        if 'enable_thinking' not in {c['name'] for c in inspect(engine).get_columns('ai_providers')}:
            with engine.begin() as connection:
                connection.execute(text('ALTER TABLE ai_providers ADD COLUMN enable_thinking BOOLEAN'))


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
