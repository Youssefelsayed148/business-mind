import hmac
import hashlib
import json

from fastapi.testclient import TestClient

from app.core.config import settings
from app.integrations.meta.webhooks import verify_meta_signature
from app.main import app
from app.api.routes_webhooks import _payload_preview

client = TestClient(app)


def test_receiver_preview_redacts_only_whatsapp_payloads():
    whatsapp = {"object": "whatsapp_business_account", "entry": [{"phone": "16315551234"}]}
    instagram = {"object": "instagram", "entry": [{"id": "visible-id"}]}
    assert _payload_preview(whatsapp) == "[redacted whatsapp_business_account payload]"
    assert "16315551234" not in _payload_preview(whatsapp)
    assert "visible-id" in _payload_preview(instagram)


def _generate_signature(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_webhook_get_returns_challenge_with_correct_token():
    response = client.get(
        "/webhooks/meta",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": settings.META_WEBHOOK_VERIFY_TOKEN,
            "hub.challenge": "test_challenge_123",
        },
    )
    assert response.status_code == 200
    assert response.text == "test_challenge_123"


def test_webhook_get_returns_403_with_wrong_token():
    response = client.get(
        "/webhooks/meta",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong_token",
            "hub.challenge": "test_challenge_123",
        },
    )
    assert response.status_code == 403


def test_verify_meta_signature_returns_true_for_valid_signature():
    body = b'{"test": true}'
    signature = _generate_signature(body, settings.META_APP_SECRET)
    assert verify_meta_signature(body, signature, settings.META_APP_SECRET) is True


def test_verify_meta_signature_returns_false_for_invalid_signature():
    body = b'{"test": true}'
    assert verify_meta_signature(body, "sha256=invalid", settings.META_APP_SECRET) is False


def test_webhook_post_rejects_missing_signature():
    response = client.post("/webhooks/meta", content=b'{}')
    assert response.status_code == 403


# This test now requires DB because the webhook POST persists events.
# It uses the conftest client fixture which overrides get_db.
from tests.conftest import skip_if_no_db


@skip_if_no_db
def test_webhook_post_accepts_valid_signature(client):
    body = json.dumps({"entry": []}).encode("utf-8")
    signature = _generate_signature(body, settings.META_APP_SECRET)
    response = client.post(
        "/webhooks/meta",
        content=body,
        headers={"X-Hub-Signature-256": signature, "Content-Type": "application/json"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "received"
