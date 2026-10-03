from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


# Look for .env in the project root (relative to this file location) or current directory.
_project_root_env = Path(__file__).resolve().parents[3] / ".env"
_env_file = _project_root_env if _project_root_env.exists() else Path(".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_env_file,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_ENV: str = "development"
    APP_NAME: str = "Instagram Automation"
    APP_SECRET_KEY: str = "change_me_local_app_secret"
    APP_BASE_URL: str = "http://localhost:8000"
    FRONTEND_URL: str = "http://localhost:3000"
    ALLOWED_ORIGINS: str = "http://localhost:3000"
    DISABLE_DOCS: bool = False
    SENTRY_DSN: str = ""

    META_APP_ID: str = "local_meta_app_id"
    META_APP_SECRET: str
    META_WEBHOOK_SECRET: str = ""
    META_WEBHOOK_VERIFY_TOKEN: str
    META_GRAPH_API_VERSION: str = "v21.0"
    META_MOCK_PRIVATE_REPLIES: bool = False

    # WhatsApp Cloud API Embedded Signup: the frontend's FB.login() call
    # needs a config_id identifying the Embedded Signup flow configured in
    # the Meta App dashboard (Business Settings > WhatsApp > Embedded
    # Signup). Uses the same META_APP_ID/META_APP_SECRET as Instagram since
    # both are products on the same Meta App.
    WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID: str = ""
    WHATSAPP_OUTREACH_ENABLED: bool = False
    WHATSAPP_HEALTH_STALE_MINUTES: int = 60
    WHATSAPP_CAMPAIGN_BREAKER_WINDOW: int = 20
    WHATSAPP_CAMPAIGN_BREAKER_FAILURE_THRESHOLD: float = 0.25
    # Empty by default: Meta send failures are retried only after an operator
    # explicitly allowlists their numeric codes (comma-separated).
    WHATSAPP_RETRYABLE_META_CODES: str = ""
    WHATSAPP_SEND_MAX_ATTEMPTS: int = 5
    WHATSAPP_SEND_RETRY_BASE_SECONDS: int = 30
    WHATSAPP_SEND_RETRY_MAX_SECONDS: int = 900
    WHATSAPP_DISPATCH_BATCH_SIZE: int = 20
    WHATSAPP_DISPATCH_TICK_SECONDS: int = 60
    WHATSAPP_DISPATCH_BACKOFF_SECONDS: int = 900
    # Redis brokers default to a 3600-second visibility timeout. Keep every
    # dispatched batch inside the much smaller window below so delayed tasks
    # are claimable well before an unacked delivery could be redelivered.
    WHATSAPP_BROKER_VISIBILITY_TIMEOUT_SECONDS: int = 3600
    WHATSAPP_DISPATCH_MAX_BATCH_WINDOW_SECONDS: int = 300
    WHATSAPP_DISPATCH_WATCHDOG_SECONDS: int = 600
    WHATSAPP_DEFER_GATE_TTL_SECONDS: int = 900
    WHATSAPP_DEFER_GATE_MAX_TTL_SECONDS: int = 86460

    # Facebook Page connection uses "Facebook Login for Business" — the same
    # config_id/FB.login() mechanism as WhatsApp's Embedded Signup, but a
    # separate config_id with its own permission scopes (pages_show_list,
    # pages_manage_metadata, pages_read_engagement, pages_manage_engagement,
    # pages_messaging) configured separately in the Meta App dashboard.
    FACEBOOK_LOGIN_CONFIG_ID: str = ""

    LOG_LEVEL: str = "INFO"

    DATABASE_URL: str
    # Dedicated test database for tests/conftest.py — MUST be a different
    # database from DATABASE_URL (setup_db() runs Base.metadata.drop_all()
    # at the end of every pytest session; see the 2026-09-17 incident in
    # conftest.py). Read from .env / env vars like every other setting.
    TEST_DATABASE_URL: str | None = None
    REDIS_URL: str = "redis://redis:6379/0"
    RATE_LIMIT_ENABLED: bool = True
    TRUST_PROXY_HEADERS: bool = False
    LOGIN_EMAIL_IP_LIMIT: int = 5
    LOGIN_EMAIL_IP_WINDOW_SECONDS: int = 60
    LOGIN_IP_LIMIT: int = 20
    LOGIN_IP_WINDOW_SECONDS: int = 900
    WEBHOOK_IP_LIMIT: int = 300
    WEBHOOK_IP_WINDOW_SECONDS: int = 60
    MUTATION_USER_LIMIT: int = 60
    MUTATION_USER_WINDOW_SECONDS: int = 60
    ACCOUNT_MUTATION_USER_LIMIT: int = 30
    ACCOUNT_MUTATION_USER_WINDOW_SECONDS: int = 60

    JWT_SECRET: str
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    TOKEN_ENCRYPTION_KEY: str = ""

    # --- AI conversation-continuation layer ---
    AI_ENABLED_GLOBAL: bool = True  # kill switch, independent of per-account toggles
    OPENAI_API_KEY: str = ""
    AI_MODEL_NAME: str = "gpt-4o-mini"
    AI_REQUEST_TIMEOUT_SECONDS: float = 15.0
    AI_MAX_CONTEXT_TURNS: int = 10


settings = Settings()


def get_allowed_origins() -> list[str]:
    return [origin.strip() for origin in settings.ALLOWED_ORIGINS.split(",") if origin.strip()]
