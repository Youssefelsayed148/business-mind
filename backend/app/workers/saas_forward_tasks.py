import logging

from datetime import datetime, timezone

from sqlalchemy import text

from app.db.session import SessionLocal, engine
from app.models.saas_forward_event import SaasForwardEvent
from app.services.saas_forwarder import process_ordering_key
from app.services.account_erasure import sweep_erasure_jobs
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.saas_forward_tasks.forward_events")
def forward_events(ordering_key: str) -> dict:
    """Deliver the pending events of one conversation in order. A Postgres
    advisory lock (held on a dedicated connection, so it survives the
    session's commits) keeps two workers from reordering one conversation."""
    with engine.connect() as lock_conn:
        got = lock_conn.execute(
            text("SELECT pg_try_advisory_lock(hashtextextended(:k, 0))"), {"k": ordering_key}
        ).scalar()
        if not got:
            return {"status": "locked"}
        try:
            db = SessionLocal()
            try:
                result = process_ordering_key(db, ordering_key)
            finally:
                db.close()
        finally:
            lock_conn.execute(
                text("SELECT pg_advisory_unlock(hashtextextended(:k, 0))"), {"k": ordering_key}
            )
            lock_conn.commit()
    if result.retry_in is not None:
        forward_events.apply_async(args=[ordering_key], countdown=max(1, int(result.retry_in) + 1))
    return {"sent": result.sent, "failed": result.failed, "dropped": result.dropped, "retry_in": result.retry_in}


@celery_app.task(name="app.workers.saas_forward_tasks.sweep_saas_forwards")
def sweep_saas_forwards() -> dict:
    """Safety net: re-kick every ordering key with a due pending event, so a
    lost task (worker crash between retries) cannot strand a queue."""
    db = SessionLocal()
    try:
        sweep_erasure_jobs(db)
        keys = [
            row[0]
            for row in db.query(SaasForwardEvent.ordering_key)
            .filter(
                SaasForwardEvent.status == "pending",
                SaasForwardEvent.next_attempt_at <= datetime.now(timezone.utc),
            )
            .distinct()
            .all()
        ]
    finally:
        db.close()
    for key in keys:
        forward_events.delay(key)
    return {"kicked": len(keys)}
