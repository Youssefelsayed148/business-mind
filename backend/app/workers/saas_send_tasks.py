import logging
from datetime import datetime, timedelta, timezone

from app.db.session import SessionLocal
from app.models.message import Message
from app.models.saas_outbound_message import SaasOutboundMessage
from app.services.saas_outbound import MESSAGE_TYPE, deliver_message
from app.services.saas_status import emit_message_status
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# 'sending' rows older than this were claimed by a worker that died; they are
# failed rather than re-sent, because the send may already have reached Meta.
STALE_SENDING = timedelta(minutes=10)


@celery_app.task(name="app.workers.saas_send_tasks.send_saas_message")
def send_saas_message(message_pk: str) -> dict:
    db = SessionLocal()
    try:
        return {"outcome": deliver_message(db, message_pk)}
    finally:
        db.close()


@celery_app.task(name="app.workers.saas_send_tasks.sweep_saas_sends")
def sweep_saas_sends() -> dict:
    """Start delivery for rows left 'queued' (broker was down at accept time)
    and fail rows stuck in 'sending' (worker died mid-send)."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        queued = [
            row[0]
            for row in db.query(Message.id)
            .join(SaasOutboundMessage, SaasOutboundMessage.message_pk == Message.id)
            .filter(Message.status == "queued", Message.created_at < now - timedelta(minutes=1))
            .all()
        ]
        stuck = (
            db.query(Message)
            .filter(
                Message.message_type == MESSAGE_TYPE,
                Message.status == "sending",
                Message.updated_at < now - STALE_SENDING,
            )
            .all()
        )
        for message in stuck:
            message.status = "failed"
            message.error_code = "unknown"
            message.error_message = "send interrupted; outcome unknown"
        db.commit()
        for message in stuck:
            emit_message_status(db, message, "failed", error_code="unknown", error_detail=message.error_message)
    finally:
        db.close()
    for pk in queued:
        send_saas_message.delay(str(pk))
    return {"requeued": len(queued), "failed_stuck": len(stuck)}
