import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import routes_auth, routes_campaigns, routes_dashboard, routes_health, routes_instagram, routes_meta, routes_messages, routes_webhooks
from app.core.config import get_allowed_origins, settings
from app.core.logging import setup_logging

logger = logging.getLogger(__name__)

setup_logging()

if settings.SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.APP_ENV,
        traces_sample_rate=0.0,
    )

docs_url = None if settings.APP_ENV == "production" and settings.DISABLE_DOCS else "/docs"
redoc_url = None if settings.APP_ENV == "production" and settings.DISABLE_DOCS else "/redoc"
openapi_url = None if settings.APP_ENV == "production" and settings.DISABLE_DOCS else "/openapi.json"

app = FastAPI(
    title=settings.APP_NAME,
    debug=settings.APP_ENV != "production",
    docs_url=docs_url,
    redoc_url=redoc_url,
    openapi_url=openapi_url,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_health.router)
app.include_router(routes_webhooks.router)
app.include_router(routes_auth.router)
app.include_router(routes_meta.router)
app.include_router(routes_instagram.router)
app.include_router(routes_campaigns.router)
app.include_router(routes_messages.router)
app.include_router(routes_dashboard.router)


@app.get("/")
async def root():
    return {
        "service": settings.APP_NAME,
        "status": "running",
    }
