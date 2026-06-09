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
    META_WEBHOOK_VERIFY_TOKEN: str
    META_GRAPH_API_VERSION: str = "v21.0"
    META_MOCK_PRIVATE_REPLIES: bool = False

    LOG_LEVEL: str = "INFO"

    DATABASE_URL: str
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


settings = Settings()


def get_allowed_origins() -> list[str]:
    return [origin.strip() for origin in settings.ALLOWED_ORIGINS.split(",") if origin.strip()]
