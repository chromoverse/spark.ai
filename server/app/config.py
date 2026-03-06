import os
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings


def _read_env_file_map() -> dict[str, str]:
    """
    Minimal `.env` parser for fallback lookups when alias fields resolve empty.
    """
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _fallback_env_value(*keys: str) -> str:
    env_map = _read_env_file_map()
    for key in keys:
        value = (os.getenv(key, "") or env_map.get(key, "")).strip()
        if value:
            return value
    return ""


class Settings(BaseSettings):
    # =========================
    # App Core
    # =========================
    port: int
    environment: str = "DESKTOP"  # "DESKTOP" | "DEVELOPMENT" | "PRODUCTION"
    db_name: str = "spark"
    default_lang: str = "en"
    ai_name: str = "SPARK"
    FRONTEND_URLS: str = "*,http://localhost:5123"

    @property
    def frontend_origins(self) -> list[str]:
        """
        Parse comma-separated frontend origins for CORS.
        Example env value:
          FRONTEND_URLS="https://app.example.com,http://localhost:5123"
        """
        raw = (self.FRONTEND_URLS or "").strip()
        if not raw:
            return ["*"]
        origins = [item.strip() for item in raw.split(",") if item.strip()]
        return origins or ["*"]

    @field_validator("environment", mode="before")
    @classmethod
    def _normalize_environment(cls, value: str) -> str:
        normalized = str(value or "").strip().upper()
        if normalized in {"DESKTOP", "DEVELOPMENT", "PRODUCTION"}:
            return normalized
        raise ValueError(
            "environment must be one of: DESKTOP, DEVELOPMENT, PRODUCTION"
        )

    @model_validator(mode="after")
    def _hydrate_cloudflare_alias_fallbacks(self) -> "Settings":
        """
        AliasChoices prefers the first present env var even when it's empty.
        Fill from legacy aliases when primary values are blank.
        """
        if not (self.cloudflare_api_token or "").strip():
            self.cloudflare_api_token = _fallback_env_value(
                "CLOUDFLARE_API_TOKEN",
                "CLOUDFLARE_API_KEY",
            )

        if not (self.cloudflare_account_id or "").strip():
            self.cloudflare_account_id = _fallback_env_value(
                "CLOUDFLARE_ACCOUNT_ID",
                "CLOUDFLARE_USER_ID",
            )

        if not (self.cloudflare_kv_namespace_id or "").strip():
            self.cloudflare_kv_namespace_id = _fallback_env_value(
                "CLOUDFLARE_KV_NAMESPACE_ID",
                "CLOUDFLARE_NAMESPACE_ID",
            )

        return self

    # =========================
    # Data Stores / Cache
    # =========================
    mongo_uri: str
    upstash_redis_rest_url: str
    upstash_redis_rest_token: str
    cloudflare_api_token: str = Field(
        default="",
        validation_alias=AliasChoices("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_API_KEY"),
    )
    cloudflare_api_email: str = Field(
        default="",
        validation_alias=AliasChoices("CLOUDFLARE_API_EMAIL", "CLOUDFLARE_EMAIL"),
    )
    cloudflare_account_id: str = Field(
        default="",
        validation_alias=AliasChoices("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_USER_ID"),
    )
    cloudflare_kv_namespace_id: str = Field(
        default="",
        validation_alias=AliasChoices(
            "CLOUDFLARE_KV_NAMESPACE_ID",
            "CLOUDFLARE_NAMESPACE_ID",
        ),
    )
    cloudflare_kv_timeout_ms: int = 3000
    cache_prod_backend: str = "cloudflare_kv"
    cache_upstash_fallback_enabled: bool = True
    cache_sync_enabled: bool = True
    cache_sync_batch_size: int = 100
    cache_sync_flush_interval_ms: int = 2000
    cache_recent_messages_limit: int = 50

    # =========================
    # AI Provider Keys + Models
    # =========================
    openrouter_api_key: str
    gemini_api_key: str
    pinecone_api_key: str
    pinecone_env: str
    pinecone_index_name: str
    pinecone_metadata_namespace: str
    HUGGINGFACE_API_ACCESS_TOKEN: str

    gemini_model_name: str
    openrouter_light_model_name: str
    openrouter_reasoning_model_name: str
    groq_mode: bool = True
    GROQ_DEFAULT_MODEL: str = "meta-llama/llama-4-scout-17b-16e-instruct"
    GROQ_REASONING_MODEL: str = "openai/gpt-oss-20b"

    # =========================
    # Search / Matching
    # =========================
    word_matching_threshold: float = 0.35

    # =========================
    # Voice / TTS Defaults
    # =========================
    ELEVEN_LABS_API_KEY: str
    nep_voice_male: str = "ne-NP-SagarNeural"
    nep_voice_female: str = "ne-NP-HemkalaNeural"
    hindi_voice_male: str = "hi-IN-MadhurNeural"
    hindi_voice_female: str = "hi-IN-SwaraNeural"
    eng_voice_male: str = "en-US-BrianNeural"
    eng_voice_female: str = "en-US-JennyNeural"

    # =========================
    # Tool CDN
    # =========================
    TOOLS_CDN_ENABLED: bool = False
    TOOLS_CDN_MANIFEST_URL: str = ""
    TOOLS_CDN_PACKAGE_URL: str = ""
    DESKTOP_TOASTS_ENABLED: bool = True

    # =========================
    # Runtime Dependency Bootstrap
    # =========================
    RUNTIME_AUTO_INSTALL_ENABLED: bool = True
    RUNTIME_AUTO_INSTALL_STRICT: bool = False
    RUNTIME_REQUIREMENTS_TIMEOUT_SEC: int = 900
    RUNTIME_PIP_INSTALL_ARGS: str = "--upgrade --no-input"
    RUNTIME_REQUIREMENTS_CORE: str = (
        "email-validator,safetensors,sentencepiece,transformers,"
        "sentence-transformers,faster-whisper,kokoro,torch"
    )
    RUNTIME_REQUIREMENTS_CPU_EXTRA: str = "onnxruntime"
    # Backend-specific extras for universal bootstrap.
    RUNTIME_REQUIREMENTS_CUDA_EXTRA: str = "onnxruntime-gpu"
    RUNTIME_REQUIREMENTS_MPS_EXTRA: str = ""
    # Legacy alias kept for backward compatibility with existing env files.
    RUNTIME_REQUIREMENTS_GPU_EXTRA: str = ""

    # =========================
    # Stream / TTS Runtime
    # =========================
    STREAM_ONE_SHOT_TTS_ENABLED: bool = True
    STREAM_FAST_ACK_ENABLED: bool = True
    STREAM_USE_LLM_STREAM: bool = True
    STREAM_USE_COMPACT_PROMPT: bool = True
    STREAM_GROQ_FAST_MODEL: str = "llama-3.1-8b-instant"

    STREAM_CONTEXT_BUDGET_MS: int = 200
    STREAM_CONTEXT_TARGET_MS: int = 100
    STREAM_CONTEXT_EMBED_BUDGET_MS: int = 35
    STREAM_CONTEXT_SEARCH_BUDGET_MS: int = 55
    STREAM_CONTEXT_TOP_K: int = 8
    STREAM_CONTEXT_CANDIDATE_LIMIT: int = 48
    STREAM_CONTEXT_MIN_RESULTS: int = 3
    STREAM_CONTEXT_LOW_SCORE: float = 0.22
    STREAM_CONTEXT_CACHE_EMPTY_RESULTS: bool = False
    STREAM_QUERY_CONTEXT_TTL_SECONDS: int = 30
    STREAM_QUERY_CONTEXT_CACHE_SIZE: int = 512

    STREAM_FIRST_AUDIO_SLO_MS: int = 1000
    STREAM_CHUNK_MIN_WORDS: int = 5
    STREAM_CHUNK_SOFT_WORDS: int = 12
    STREAM_CHUNK_MAX_WORDS: int = 30

    FINAL_STATE_SUMMARY_TTS_ENABLED: bool = True
    FINAL_STATE_SUMMARY_LLM_TIMEOUT_MS: int = 1000
    SQH_PLAN_RETRY_ATTEMPTS: int = 1
    pinecone_integrated_embeddings_prod: bool = True


    class Config:
        env_file = ".env"
        env_ignore_empty = True
        extra = "ignore"

    @property
    def CLOUDFLARE_API_KEY(self) -> str:
        """
        Backward-compatible alias for legacy codepaths expecting uppercase setting.
        """
        return self.cloudflare_api_token


settings = Settings()  # type: ignore
