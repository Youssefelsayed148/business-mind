import logging

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.integrations.meta.webhooks import verify_meta_signature
from app.services.webhook_event_service import store_webhook_event
from app.services.rate_limit_service import enforce_ip_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/webhooks/meta")
async def meta_webhook_get(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == settings.META_WEBHOOK_VERIFY_TOKEN:
        return PlainTextResponse(content=hub_challenge, status_code=200)
    return Response(status_code=403)


@router.post("/webhooks/meta")
async def meta_webhook_post(request: Request, db: Session = Depends(get_db)):
    enforce_ip_rate_limit(
        request,
        "webhook_meta",
        settings.WEBHOOK_IP_LIMIT,
        settings.WEBHOOK_IP_WINDOW_SECONDS,
        "Too many webhook requests. Please try again later.",
    )
    raw_body = await request.body()
    signature_header = request.headers.get("X-Hub-Signature-256")

    # Instagram-Login webhooks are signed with the Instagram app secret,
    # Page/WhatsApp webhooks with the Facebook app secret; accept either.
    if not any(verify_meta_signature(raw_body, signature_header, s) for s in settings.webhook_secrets):
        return Response(status_code=403)

    payload = await request.json()
    logger.info("Webhook payload received", extra={"payload_summary": str(payload)[:500]})

    event = store_webhook_event(db, payload, raw_body, signature_valid=True)
    if event is None:
        return {"status": "duplicate"}

    # Enqueue async processing
    try:
        from app.workers.tasks import process_webhook_event

        process_webhook_event.delay(str(event.id))
        logger.info("Enqueued webhook processing", extra={"event_id": str(event.id)})
    except Exception:
        logger.exception("Failed to enqueue webhook processing", extra={"event_id": str(event.id)})

    return {"status": "received"}