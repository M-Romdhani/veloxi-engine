"""Application configuration (env-driven, with safe defaults)."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Storage
    database_url: str = "sqlite:///./veloxi.db"

    # Admin auth (single shared token). Empty => the admin API stays locked.
    admin_token: str = ""

    # Background pipeline. Off by default => clean offline boot, no network noise.
    ingest_enabled: bool = False
    validate_interval_minutes: int = 15
    ingest_interval_minutes: int = 60
    validation_batch_size: int = 25
    validation_fail_threshold: int = 3
    request_timeout_seconds: float = 8.0
    # Identify the fetcher politely; some feeds reject obvious bot/empty agents.
    http_user_agent: str = "Mozilla/5.0 (compatible; VeloxiBot/1.0; +https://github.com/M-Romdhani/veloxi-engine)"

    # Apify (optional). Token via env; actors run synchronously and can be slow.
    apify_token: str = ""
    apify_timeout_seconds: float = 180.0

    # Promotion policy
    auto_promote: bool = True
    auto_promote_min_confidence: float = 0.15

    # Optional LLM classifier. "" => heuristic only (free, no key).
    llm_provider: str = ""  # anthropic | openai | gemini | ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5-20251001"
    openai_model: str = "gpt-4o-mini"
    gemini_model: str = "gemini-2.5-flash"

    @property
    def llm_enabled(self) -> bool:
        provider = (self.llm_provider or "").strip().lower()
        key = {
            "anthropic": self.anthropic_api_key,
            "openai": self.openai_api_key,
            "gemini": self.gemini_api_key,
        }.get(provider, "")
        return bool(provider) and bool(key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
