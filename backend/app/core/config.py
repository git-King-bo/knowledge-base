from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = Field(default="Knowledge Base API", alias="APP_NAME")
    app_env: str = Field(default="local", alias="APP_ENV")
    app_host: str = Field(default="127.0.0.1", alias="APP_HOST")
    app_port: int = Field(default=8001, alias="APP_PORT")
    app_cors_origins: str = Field(
        default=(
            "http://localhost:5173,http://127.0.0.1:5173,"
            "http://localhost:5174,http://127.0.0.1:5174,"
            "http://localhost:5175,http://127.0.0.1:5175"
        ),
        alias="APP_CORS_ORIGINS",
    )
    database_url: str = Field(default="sqlite:///./knowledge_base.db", alias="DATABASE_URL")
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

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.app_cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
