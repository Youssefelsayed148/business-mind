"""POST /api/saas/messages - the SaaS asks Many to send a message (M-03).

Authentication failures of every kind (unknown/revoked/unlinked connection,
delegation off, bad or stale signature, oversized body) return one identical
generic 401. Behind the proxy the public /api prefix is stripped, so the
router is mounted at both /saas and /api/saas.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services import saas_delegation_service as delegation
from app.services import saas_health, saas_outbound
from app.services.saas_signing import (
    HEADER_CONNECTION,
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    MAX_BODY_BYTES,
    compute_signature,
    verify_signature,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_UNAUTHORIZED = {"detail": "unauthorized"}
_DUMMY_SECRET = "x" * 40


class SaasMessageIn(BaseModel):
    message_id: str = Field(min_length=1, max_length=128)
    connection_id: str = Field(min_length=1, max_length=64)
    external_contact_id: str = Field(min_length=1, max_length=255)
    external_conversation_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1)
    kind: str


def unauthorized(reason: str) -> JSONResponse:
    # The reason is logged (never secrets or message text), not returned.
    logger.info("SaaS request rejected", extra={"reason": reason})
    return JSONResponse(_UNAUTHORIZED, status_code=401)


def authenticate(db: Session, request: Request, body: bytes):
    """(platform, channel) for a correctly signed request, else None after
    logging why. Always does one HMAC computation so an unknown connection is
    not cheaper to reject than a bad signature."""
    connection_id = request.headers.get(HEADER_CONNECTION, "")
    timestamp = request.headers.get(HEADER_TIMESTAMP)
    signature = request.headers.get(HEADER_SIGNATURE)
    found = saas_outbound.find_channel(db, connection_id)
    if found is None:
        compute_signature(_DUMMY_SECRET, timestamp or "0", body)
        return None, "unknown_connection"
    platform, channel = found
    current, previous = delegation.get_secrets(channel)
    secrets = [s for s in (current, previous) if s]
    if not verify_signature(secrets, timestamp, signature, body):
        return None, "bad_signature_or_timestamp"
    return found, None


@router.post("/messages", status_code=202)
async def receive_message(request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        return unauthorized("body_too_large")
    found, reason = authenticate(db, request, body)
    if found is None:
        return unauthorized(reason)
    platform, channel = found

    try:
        payload = SaasMessageIn.model_validate_json(body)
    except ValidationError:
        raise HTTPException(status_code=422, detail="invalid body")
    if payload.connection_id != request.headers.get(HEADER_CONNECTION):
        return unauthorized("connection_mismatch")
    if payload.kind not in saas_outbound.KINDS:
        raise HTTPException(status_code=422, detail="unsupported kind")

    try:
        accepted = saas_outbound.accept_message(
            db,
            platform=platform,
            channel=channel,
            connection_id=payload.connection_id,
            message_id=payload.message_id,
            external_contact_id=payload.external_contact_id,
            external_conversation_id=payload.external_conversation_id,
            text=payload.text,
            kind=payload.kind,
        )
    except saas_outbound.RequestRejected:
        raise HTTPException(status_code=404, detail="not found")

    if not accepted.duplicate:
        _start_delivery(str(accepted.message_pk))
    return {"id": str(accepted.many_id)}


def _start_delivery(message_pk: str) -> None:
    """A broker outage must not turn an accepted message into an error: the
    sweep re-queues anything still 'queued'."""
    try:
        from app.workers.saas_send_tasks import send_saas_message

        send_saas_message.delay(message_pk)
    except Exception:
        logger.warning("Could not start SaaS send task; sweep will retry", exc_info=True)


@router.get("/connections/{connection_id}/health")
async def connection_health(connection_id: str, request: Request, db: Session = Depends(get_db)):
    """Signed pull of channel health (contract 5.2). The signature covers
    `timestamp + "."` (empty body). Same generic 401 as every other failure;
    the path id must be the signed connection. Reads Many's own state only."""
    body = await request.body()
    if body:
        return unauthorized("unexpected_body")
    if request.headers.get(HEADER_CONNECTION, "") != connection_id:
        return unauthorized("path_connection_mismatch")
    found, reason = authenticate(db, request, body)
    if found is None:
        return unauthorized(reason)
    platform, channel = found
    return saas_health.health_body(db, platform, channel)
