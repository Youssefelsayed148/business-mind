import logging

from app.db.session import SessionLocal
from app.services.saas_forwarder import purge_expired
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.saas_retention_tasks.purge_saas_data")
def purge_saas_data() -> dict:
    """Daily retention: clear old failed-event payloads, delete old terminal
    forward rows and old outbound idempotency records."""
    db = SessionLocal()
    try:
        result = purge_expired(db)
    finally:
        db.close()
    logger.info(
        "SaaS retention sweep",
        extra={
            "payloads_cleared": result.payloads_cleared,
            "events_deleted": result.events_deleted,
            "outbound_deleted": result.outbound_deleted,
        },
    )
    return {
        "payloads_cleared": result.payloads_cleared,
        "events_deleted": result.events_deleted,
        "outbound_deleted": result.outbound_deleted,
    }
