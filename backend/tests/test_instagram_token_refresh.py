from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest

from app.integrations.meta import token_refresh
from app.integrations.meta.errors import MetaAPIError
from app.models.automation_log import AutomationLog
from app.models.instagram_account import InstagramAccount
from app.models.meta_token import MetaToken
from app.models.workspace import Workspace
from app.services import token_service
from app.utils.crypto import decrypt_text, encrypt_text
from app.workers import instagram_token_tasks
from app.workers.celery_app import celery_app

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def _make_token(db, *, expires_in_days, age_days=30, status="active", plain="old-token"):
    ws = Workspace(id=uuid4(), name="Default", slug=f"tok-{uuid4().hex[:8]}")
    db.add(ws)
    db.flush()  # Resolve the parent FK before inserting the account.
    account = InstagramAccount(
        id=uuid4(), workspace_id=ws.id, ig_user_id=f"ig-{uuid4().hex[:8]}", ig_username="shop"
    )
    db.add(account)
    db.commit()
    issued = NOW - timedelta(days=age_days)
    token = MetaToken(
        instagram_account_id=account.id,
        access_token=encrypt_text(plain),
        token_type="long_lived",
        status=status,
        expires_at=NOW + timedelta(days=expires_in_days),
        created_at=issued,
        updated_at=issued,
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return account, token


class _Response:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeClient:
    calls: list = []
    response = _Response(200, {"access_token": "new-token", "token_type": "bearer", "expires_in": 5183944})

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, params=None):
        _FakeClient.calls.append((url, dict(params or {})))
        return _FakeClient.response


@pytest.fixture
def fake_httpx(monkeypatch):
    _FakeClient.calls = []
    _FakeClient.response = _Response(
        200, {"access_token": "new-token", "token_type": "bearer", "expires_in": 5183944}
    )
    monkeypatch.setattr(token_refresh.httpx, "Client", _FakeClient)
    return _FakeClient


def test_refresh_long_lived_token_calls_documented_endpoint(fake_httpx):
    data = token_refresh.refresh_long_lived_token("old-token")
    assert data["access_token"] == "new-token"
    url, params = fake_httpx.calls[0]
    assert url == "https://graph.instagram.com/refresh_access_token"
    assert params == {"grant_type": "ig_refresh_token", "access_token": "old-token"}


def test_refresh_long_lived_token_raises_on_meta_error(fake_httpx):
    fake_httpx.response = _Response(400, {"error": {"message": "Session has expired", "code": 190}})
    with pytest.raises(MetaAPIError, match="Session has expired"):
        token_refresh.refresh_long_lived_token("old-token")


def test_refresh_long_lived_token_network_error_does_not_leak_token(monkeypatch):
    class _Boom(_FakeClient):
        def get(self, url, params=None):
            raise httpx.ConnectError("GET https://graph.instagram.com/refresh_access_token?access_token=SECRET")

    monkeypatch.setattr(token_refresh.httpx, "Client", _Boom)
    with pytest.raises(MetaAPIError) as exc:
        token_refresh.refresh_long_lived_token("SECRET")
    assert "SECRET" not in str(exc.value)


def test_refresh_token_success_stores_new_encrypted_token_and_expiry(db_session, fake_httpx):
    _, token = _make_token(db_session, expires_in_days=5)
    assert token_service.refresh_token(db_session, token, now=NOW) == "refreshed"
    db_session.refresh(token)
    assert decrypt_text(token.access_token) == "new-token"
    assert token.access_token != "new-token"
    assert token.status == "active"
    assert token.expires_at == NOW + timedelta(seconds=5183944)


def test_refresh_token_failure_keeps_old_token_and_stays_active(db_session, fake_httpx):
    fake_httpx.response = _Response(400, {"error": {"message": "bad", "code": 100}})
    _, token = _make_token(db_session, expires_in_days=5)
    original = token.access_token
    assert token_service.refresh_token(db_session, token, now=NOW) == "failed"
    db_session.refresh(token)
    assert token.access_token == original
    # Send paths only read status "active"; a failed refresh must not stop a still-valid token.
    assert token.status == "active"


def test_refresh_token_too_young_is_not_sent_to_meta(db_session, fake_httpx):
    _, token = _make_token(db_session, expires_in_days=5, age_days=0)
    token.updated_at = NOW - timedelta(hours=2)
    db_session.commit()
    assert token_service.refresh_token(db_session, token, now=NOW) == "too_young"
    assert fake_httpx.calls == []


def test_refresh_token_already_expired_is_marked_expired_without_calling_meta(db_session, fake_httpx):
    _, token = _make_token(db_session, expires_in_days=-1)
    assert token_service.refresh_token(db_session, token, now=NOW) == "expired"
    db_session.refresh(token)
    assert token.status == "expired"
    assert fake_httpx.calls == []


def test_get_tokens_expiring_within_filters(db_session):
    real_now = datetime.now(timezone.utc)
    _, soon = _make_token(db_session, expires_in_days=3)
    _, far = _make_token(db_session, expires_in_days=40)
    soon.expires_at = real_now + timedelta(days=3)
    far.expires_at = real_now + timedelta(days=40)
    _, no_expiry = _make_token(db_session, expires_in_days=3)
    no_expiry.expires_at = None
    _, expired = _make_token(db_session, expires_in_days=3, status="expired")
    expired.expires_at = real_now + timedelta(days=1)
    db_session.commit()
    ids = {t.id for t in token_service.get_tokens_expiring_within(db_session, 10)}
    assert soon.id in ids
    assert far.id not in ids
    assert no_expiry.id not in ids
    assert expired.id not in ids


def test_task_refreshes_logs_and_never_logs_token(db_session, fake_httpx, monkeypatch):
    monkeypatch.setattr(instagram_token_tasks, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    ok_account, ok = _make_token(db_session, expires_in_days=3)
    ok.expires_at = datetime.now(timezone.utc) + timedelta(days=3)
    ok.created_at = ok.updated_at = datetime.now(timezone.utc) - timedelta(days=50)
    db_session.commit()
    counts = instagram_token_tasks.refresh_expiring_instagram_tokens.run()
    assert counts["refreshed"] >= 1
    logs = (
        db_session.query(AutomationLog)
        .filter(AutomationLog.instagram_account_id == ok_account.id)
        .all()
    )
    assert [log.action for log in logs] == ["token_refreshed"]
    assert "new-token" not in str(logs[0].details) and "old-token" not in str(logs[0].details)


def test_task_logs_failure(db_session, fake_httpx, monkeypatch):
    monkeypatch.setattr(instagram_token_tasks, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    fake_httpx.response = _Response(500, {"error": {"message": "boom"}})
    account, token = _make_token(db_session, expires_in_days=3)
    token.expires_at = datetime.now(timezone.utc) + timedelta(days=3)
    token.created_at = token.updated_at = datetime.now(timezone.utc) - timedelta(days=50)
    db_session.commit()
    counts = instagram_token_tasks.refresh_expiring_instagram_tokens.run()
    assert counts["failed"] >= 1
    actions = [
        log.action
        for log in db_session.query(AutomationLog).filter(
            AutomationLog.instagram_account_id == account.id
        )
    ]
    assert actions == ["token_refresh_failed"]


def test_schedule_is_registered_on_celery_app():
    entry = celery_app.conf.beat_schedule["instagram-token-refresh"]
    assert entry["task"] == "app.workers.instagram_token_tasks.refresh_expiring_instagram_tokens"
    celery_app.loader.import_default_modules()
    assert entry["task"] in celery_app.tasks


def test_no_dead_beat_schedule_module():
    with pytest.raises(ImportError):
        __import__("app.workers.beat_schedule")


def test_account_response_includes_token_expiry(db_session):
    from app.api.routes_instagram import _account_response

    account, token = _make_token(db_session, expires_in_days=20)
    assert _account_response(account, db_session)["expires_at"] == token.expires_at.isoformat()
