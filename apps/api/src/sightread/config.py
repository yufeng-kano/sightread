"""Environment settings. `.env.example` at the repo root is the authoritative variable list."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Only ever used when APP_ENV=local and SECRET_KEY is unset, so `uv run uvicorn` works
# without a .env file. Production refuses to start without a real SECRET_KEY.
LOCAL_FALLBACK_SECRET_KEY = "local-development-insecure-secret-key"  # noqa: S105


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    app_env: Literal["local", "production"] = "local"
    app_url: str = "http://localhost:8000"
    web_url: str = "http://localhost:3000"
    # The web app's non-default locale prefixes, comma-separated, mirroring its i18n config
    # (apps/web/nuxt.config.ts uses `prefix_except_default`, so the default locale has none).
    # Sign-in returns the visitor to `WEB_URL/<prefix>` when they picked one; a value outside
    # this list is ignored, which is what keeps the return destination un-forgeable.
    web_locale_prefixes: str = "zh-TW"

    database_url: str = "postgresql+asyncpg://sightread:sightread@localhost:5432/sightread"
    postgres_user: str = "sightread"
    postgres_password: str = "sightread"  # noqa: S105 - compose default, not a secret
    postgres_db: str = "sightread"

    secret_key: str = ""

    google_client_id: str = ""
    google_client_secret: str = ""

    auth_dev_mode: bool = False

    upload_max_bytes: int = 134_217_728
    page_cap: int = 500
    max_jobs_per_user: int = 2
    vision_concurrency_per_job: int = 8
    render_workers: int = 0  # 0 means "CPU count", resolved by the worker
    upload_dir: str = "/data/uploads"
    # Cap on a user's custom system prompt (docs/api.md § Limits).
    system_prompt_max_chars: int = 8000
    # Cap on any upstream response body — a user-controlled endpoint must not be able to
    # exhaust memory with an unbounded reply (docs/parsing.md § Upstream usage).
    upstream_response_max_bytes: int = 33_554_432
    # Upload tickets minted by the MCP `parse` tool (docs/auth.md § 5).
    upload_ticket_ttl_seconds: int = 3600
    upload_ticket_rate_per_hour: int = 30

    domain: str = ""
    acme_email: str = ""

    @model_validator(mode="after")
    def _check_secrets(self) -> Settings:
        if not self.secret_key:
            if self.app_env != "local":
                raise ValueError("SECRET_KEY is required when APP_ENV is not 'local'")
            self.secret_key = LOCAL_FALLBACK_SECRET_KEY
        return self

    @property
    def dev_login_enabled(self) -> bool:
        """`POST /api/auth/dev-login` exists only under both conditions (docs/auth.md)."""
        return self.app_env == "local" and self.auth_dev_mode

    @property
    def google_oidc_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    def web_url_for_locale(self, prefix: str) -> str:
        """`WEB_URL`, prefixed when the visitor picked a non-default locale.

        An unknown prefix is not an error, it is simply the default locale: the value
        reaches us from a query string, so treating it as an allowlist rather than as a
        path fragment is what stops it becoming an open redirect (docs/auth.md § 1).
        """
        allowed = {item.strip() for item in self.web_locale_prefixes.split(",") if item.strip()}
        return f"{self.web_url}/{prefix}" if prefix in allowed else self.web_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
