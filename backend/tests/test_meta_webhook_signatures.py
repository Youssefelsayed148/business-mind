"""POST /webhooks/meta accepts payloads signed with either the Instagram app
secret or the Facebook app secret, and rejects everything else."""

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

IG_SECRET = "ig_app_secret_for_test"
FB_SECRET = "fb_app_secret_for_test"
BODY = json.dumps({"object": "instagram", "entry": [{"id": "1", "time": 1}]}).encode()


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture
def webhook(monkeypatch):
    monkeypatch.setattr(settings, "META_APP_SECRET", IG_SECRET)
    monkeypatch.setattr(settings, "META_WEBHOOK_SECRET", "")
    monkeypatch.setattr(settings, "FACEBOOK_APP_SECRET", FB_SECRET)
    # Past the signature gate, report a duplicate so no DB or broker is touched.
    monkeypatch.setattr("app.api.routes_webhooks.store_webhook_event", lambda *a, **k: None)
    client = TestClient(app)

    def post(signature: str | None):
        headers = {"Content-Type": "application/json"}
        if signature is not None:
            headers["X-Hub-Signature-256"] = signature
        return client.post("/webhooks/meta", content=BODY, headers=headers)

    return post


def test_signed_with_instagram_secret_is_accepted(webhook):
    response = webhook(_sign(BODY, IG_SECRET))
    assert response.status_code == 200
    assert response.json() == {"status": "duplicate"}


def test_signed_with_facebook_app_secret_is_accepted(webhook):
    response = webhook(_sign(BODY, FB_SECRET))
    assert response.status_code == 200
    assert response.json() == {"status": "duplicate"}


def test_signed_with_wrong_secret_is_rejected(webhook):
    assert webhook(_sign(BODY, "not_either_secret")).status_code == 403


def test_missing_signature_header_is_rejected(webhook):
    assert webhook(None).status_code == 403
