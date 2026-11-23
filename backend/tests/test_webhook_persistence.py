import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.webhook_event import WebhookEvent
from app.services.webhook_event_service import derive_external_event_id
from tests.conftest import skip_if_no_db


def _generate_signature(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


@skip_if_no_db
def test_webhook_post_stores_event(client: TestClient, db_session: Session):
    body = json.dumps({"entry": [{"id": "123", "changes": [{"field": "mentions"}]}]}).encode("utf-8")
    signature = _generate_signature(body, settings.META_APP_SECRET)

    response = client.post(
        "/webhooks/meta",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "received"

    events = db_session.query(WebhookEvent).all()
    assert len(events) >= 1
    assert events[-1].provider == "meta"
    assert events[-1].processing_status == "pending"


@skip_if_no_db
def test_duplicate_webhook_post_does_not_duplicate_event(
    client: TestClient, db_session: Session
):
    body = json.dumps({"entry": [{"id": "456", "changes": [{"field": "mentions"}]}]}).encode("utf-8")
    signature = _generate_signature(body, settings.META_APP_SECRET)

    response1 = client.post(
        "/webhooks/meta",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
        },
    )
    assert response1.json()["status"] == "received"

    response2 = client.post(
        "/webhooks/meta",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
        },
    )
    assert response2.json()["status"] == "duplicate"


@skip_if_no_db
def test_invalid_webhook_signature_rejected(client: TestClient):
    body = b'{}'
    response = client.post(
        "/webhooks/meta",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": "sha256=invalid",
        },
    )
    assert response.status_code == 403


def test_external_event_id_fallback_hash_is_deterministic():
    payload = {"some": "data"}
    raw_body = b'{"some":"data"}'
    id1 = derive_external_event_id(payload, raw_body)
    id2 = derive_external_event_id(payload, raw_body)
    assert id1 == id2
    assert len(id1) == 64  # sha256 hex
