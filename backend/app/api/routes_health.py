import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from redis import Redis
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.webhook_health import WebhookHealth

logger = logging.getLogger(__name__)

router = APIRouter()


def check_database(db: Session) -> bool:
    db.execute(text("SELECT 1"))
    return True


def check_redis() -> bool:
    client = Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2)
    try:
        return bool(client.ping())
    finally:
        client.close()


def _webhook_status(last_event_at: datetime | None, consecutive_failures: int) -> str:
    if consecutive_failures >= 3:
        return "alert"
    if last_event_at is None:
        return "unknown"
    if last_event_at < datetime.now(timezone.utc) - timedelta(hours=24):
        return "unknown"
    return "ok"


@router.get("/health")
async def health(db: Session = Depends(get_db)):
    database_ok = False
    redis_ok = False
    try:
        database_ok = check_database(db)
    except Exception:
        logger.exception("Database health check failed")
    try:
        redis_ok = check_redis()
    except Exception:
        logger.exception("Redis health check failed")

    status_code = 200 if database_ok and redis_ok else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ok" if status_code == 200 else "error",
            "service": settings.APP_NAME,
            "environment": settings.APP_ENV,
            "app": "ok",
            "database": "ok" if database_ok else "error",
            "redis": "ok" if redis_ok else "error",
        },
    )


@router.get("/webhooks/health")
async def webhooks_health(db: Session = Depends(get_db)):
    health_record = (
        db.query(WebhookHealth)
        .filter(WebhookHealth.provider == "meta")
        .order_by(WebhookHealth.updated_at.desc())
        .first()
    )
    last_event_at = health_record.last_webhook_at if health_record else None
    consecutive_failures = health_record.consecutive_failures if health_record else 0

    worker_health = "unknown"
    try:
        redis_ok = check_redis()
        worker_health = "ok" if redis_ok else "unknown"
    except Exception:
        logger.exception("Worker health probe failed")

    return {
        "status": _webhook_status(last_event_at, consecutive_failures),
        "last_event_received_at": last_event_at.isoformat() if last_event_at else None,
        "worker_health": worker_health,
        "webhook_status": _webhook_status(last_event_at, consecutive_failures),
        "consecutive_failures": consecutive_failures,
    }
