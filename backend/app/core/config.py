from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    auth_enabled: bool = Field(default=True, alias="APP_AUTH_ENABLED")
    encryption_key: str = Field(default="", alias="APP_ENCRYPTION_KEY")
    security_dir: str = Field(default="storage/security", alias="APP_SECURITY_DIR")
    provider_allowed_hosts: str = Field(default="", alias="APP_PROVIDER_ALLOWED_HOSTS")
    allow_private_providers: bool = Field(default=False, alias="APP_ALLOW_PRIVATE_PROVIDERS")
    session_hours: int = Field(default=12, ge=1, le=168, alias="APP_SESSION_HOURS")
    worker_enabled: bool = Field(default=True, alias="APP_WORKER_ENABLED")
    requests_per_minute: int = Field(default=60, ge=1, alias="APP_REQUESTS_PER_MINUTE")
    model_requests_per_day: int = Field(default=200, ge=1, alias="APP_MODEL_REQUESTS_PER_DAY")
    daily_token_budget: int = Field(default=2000000, ge=1, alias="APP_DAILY_TOKEN_BUDGET")
    model_max_output_tokens: int = Field(default=2048, ge=128, le=8192, alias="APP_MAX_OUTPUT_TOKENS")
    model_concurrency: int = Field(default=4, ge=1, le=32, alias="APP_MODEL_CONCURRENCY")
    max_pending_jobs: int = Field(default=20, ge=1, alias="APP_MAX_PENDING_JOBS")
    log_retention_days: int = Field(default=30, ge=1, alias="APP_LOG_RETENTION_DAYS")
    ocr_enabled: bool = Field(default=False, alias="APP_OCR_ENABLED")
    app_name: str = Field(default="Knowledge Base API", alias="APP_NAME")
    app_env: str = Field(default="local", alias="APP_ENV")
    app_host: str = Field(default="127.0.0.1", alias="APP_HOST")
    app_port: int = Field(default=8001, alias="APP_PORT")
    app_cors_origins: str = Field(
        default=(
            "http://localhost:5173,http://127.0.0.1:5173,"
            "http://localhost:5174,http://127.0.0.1:5174,"
            "http://localhost:5175,http://127.0.0.1:5175,"
            "http://localhost:5177,http://127.0.0.1:5177"
        ),
        alias="APP_CORS_ORIGINS",
    )
    database_url: str = Field(default="sqlite:///./knowledge_base.db", alias="DATABASE_URL")
    # auto：启动时优先尝试 MySQL，连接失败则固定使用 SQLite，运行中不切库。
    database_mode: Literal['auto', 'mysql', 'sqlite'] = Field(default='auto', alias='APP_DATABASE_MODE')
    sqlite_fallback_url: str = Field(default='sqlite:///./knowledge_base.db', alias='APP_SQLITE_FALLBACK_URL')
    mysql_host: str = Field(default='', alias='XINIU_MYSQL_HOST')
    mysql_port: int = Field(default=3306, ge=1, le=65535, alias='XINIU_MYSQL_PORT')
    mysql_database: str = Field(default='', alias='XINIU_MYSQL_DATABASE')
    mysql_user: str = Field(default='', alias='XINIU_MYSQL_USER')
    mysql_password: SecretStr = Field(default=SecretStr(''), alias='XINIU_MYSQL_PASSWORD')
    mysql_connect_timeout: int = Field(default=5, ge=1, le=30, alias='APP_MYSQL_CONNECT_TIMEOUT')
    upload_dir: str = Field(default="storage/uploads", alias="APP_UPLOAD_DIR")
    knowledge_chunk_max_chars: int = Field(default=480, alias="APP_KB_CHUNK_MAX_CHARS")
    knowledge_chunk_overlap_chars: int = Field(default=80, alias="APP_KB_CHUNK_OVERLAP_CHARS")
    knowledge_hybrid_lexical_weight: float = Field(default=0.45, alias="APP_KB_HYBRID_LEXICAL_WEIGHT")
    knowledge_hybrid_embedding_weight: float = Field(default=0.55, alias="APP_KB_HYBRID_EMBEDDING_WEIGHT")
    embedding_api_url: str = Field(default="", alias="AGENT_EMBEDDING_API_URL")
    embedding_api_key: str = Field(default="", alias="AGENT_EMBEDDING_API_KEY")
    embedding_model: str = Field(default="text-embedding-3-small", alias="AGENT_EMBEDDING_MODEL")
    embedding_batch_size: int = Field(default=16, alias="APP_KB_EMBEDDING_BATCH_SIZE")
    default_ai_provider: str = Field(default="mock", alias="DEFAULT_AI_PROVIDER")
    default_api_url: str = Field(default="", alias="AGENT_DEFAULT_API_URL")
    default_api_key: str = Field(default="", alias="AGENT_DEFAULT_API_KEY")
    default_api_model: str = Field(default="qwen-plus", alias="AGENT_DEFAULT_MODEL")
    web_search_enabled: bool = Field(default=False, alias="WEB_SEARCH_ENABLED")
    web_search_provider: str = Field(default="tavily", alias="WEB_SEARCH_PROVIDER")
    web_search_api_key: str = Field(default="", alias="WEB_SEARCH_API_KEY")
    web_search_max_results: int = Field(default=5, alias="WEB_SEARCH_MAX_RESULTS")
    web_search_timeout_seconds: float = Field(default=10.0, alias="WEB_SEARCH_TIMEOUT_SECONDS")
    web_search_auto_threshold: float = Field(default=0.35, alias="WEB_SEARCH_AUTO_THRESHOLD")

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.app_cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
