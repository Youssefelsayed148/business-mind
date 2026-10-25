import logging

from app.db.session import SessionLocal
from app.services.saas_health import sync_all
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.saas_health_tasks.sweep_saas_health")
def sweep_saas_health() -> dict:
    """Push channel.status on every transition (compared against the last
    pushed status) and as a heartbeat. Reads only Many's own state."""
    db = SessionLocal()
    try:
        return {"queued": sync_all(db)}
    finally:
        db.close()
