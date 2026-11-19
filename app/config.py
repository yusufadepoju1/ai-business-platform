"""Application settings, loaded from environment variables / .env file."""
from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_env: str = "development"  # development | production | test
    secret_key: str = "dev-only-insecure-secret-change-me"
    access_token_expire_minutes: int = 60 * 12
    database_url: str = "sqlite:///./dev.db"
    auto_create_tables: bool = False  # tests / quick-start only; use Alembic otherwise

    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    embedding_provider: str = "auto"  # auto | sentence-transformers | hashing
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    vector_dir: str = "./data/vectors"
    max_upload_mb: int = 10
    chunk_size: int = 800
    chunk_overlap: int = 120

    cors_origins: str = ""  # comma separated; empty = same-origin only
    public_base_url: str = "http://localhost:8000"

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True

    allow_private_webhook_targets: bool = True  # set false on public hosting
    async_dispatch: bool = True  # deliver webhooks/emails in background threads
    rate_limit_enabled: bool = True
    log_level: str = "INFO"

    @field_validator("database_url")
    @classmethod
    def _normalize_db(cls, v: str) -> str:
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://"):]
        if v.startswith("postgresql://"):
            v = "postgresql+psycopg2://" + v[len("postgresql://"):]
        return v

    @property
    def cors_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
