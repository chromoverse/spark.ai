from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# brain/app/core/config.py → repo root. Missing in the container, which gets env from compose.
_ENV_FILE = Path(__file__).resolve().parents[3] / "deploy" / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    env: Literal["dev", "prod", "test"] = "dev"
    public_url: str = "http://localhost:8080"
    database_url: str = "postgresql+asyncpg://spark:spark@127.0.0.1:5432/spark"
    redis_url: str = "redis://127.0.0.1:6379/0"
    searxng_url: str = "http://127.0.0.1:8888"

    jwt_secret: SecretStr
    jwt_secret_previous: SecretStr | None = None
    encryption_master_key: SecretStr | None = None  # first used in R4 (OAuth tokens, BYOK)

    cors_origins: str = "http://localhost:5123"
    paid_providers_enabled: bool = False
    allow_training_providers_default: bool = False

    resend_api_key: SecretStr = SecretStr("")
    mail_from: str = "Spark <onboarding@resend.dev>"
    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")

    # LLM provider keys, comma-separated (several keys per provider rotate on rate limits).
    groq_api_keys: SecretStr = SecretStr("")
    nvidia_api_keys: SecretStr = SecretStr("")
    cloudflare_account_id: str = ""
    cloudflare_api_tokens: SecretStr = SecretStr("")
    mistral_api_keys: SecretStr = SecretStr("")
    gemini_api_keys: SecretStr = SecretStr("")
    openrouter_api_keys: SecretStr = SecretStr("")
    anthropic_api_key: SecretStr = SecretStr("")  # read only when paid_providers_enabled

    log_level: str = "INFO"

    @field_validator("jwt_secret")
    @classmethod
    def _strong_secret(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")
        return v

    @field_validator("cors_origins")
    @classmethod
    def _no_wildcard(cls, v: str) -> str:
        if "*" in v:
            raise ValueError("CORS_ORIGINS must list app origins, never '*'")
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]
