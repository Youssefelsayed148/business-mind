"""verify_user_access_token (httpx mocked) and the /facebook/connect/callback
guard that a failed verification stops the connect flow before any exchange."""

import asyncio
from uuid import uuid4

import httpx
import pytest
from redis import Redis
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.integrations.meta import facebook_oauth
from app.integrations.meta.errors import MetaAPIError
from app.models.facebook_page import FacebookPage
from app.models.user import User
from app.models.user_workspace_membership import UserWorkspaceMembership
from app.models.workspace import Workspace
from tests.conftest import skip_if_no_db

APP_ID = "fb_app_123"


@pytest.fixture
def mock_graph(monkeypatch):
    """Route facebook_oauth's httpx.AsyncClient through a MockTransport that
    answers every request with the configured (status, body)."""
    monkeypatch.setattr(settings, "FACEBOOK_APP_ID", APP_ID)
    monkeypatch.setattr(settings, "FACEBOOK_APP_SECRET", "fb_secret")
    real_client = httpx.AsyncClient
    seen: list[httpx.Request] = []

    def install(status: int, body):
        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            if isinstance(body, bytes):
                return httpx.Response(status, content=body)
            return httpx.Response(status, json=body)

        monkeypatch.setattr(
            facebook_oauth.httpx,
            "AsyncClient",
            lambda *a, **k: real_client(transport=httpx.MockTransport(handler)),
        )
        return seen

    return install


def _verify(token="user_token"):
    return asyncio.run(facebook_oauth.verify_user_access_token(token))


def test_verify_accepts_valid_token_for_our_app(mock_graph):
    seen = mock_graph(200, {"data": {"is_valid": True, "app_id": APP_ID}})
    assert _verify("user_token") is None
    assert len(seen) == 1
    assert seen[0].url.path.endswith("/debug_token")
    assert seen[0].url.params["input_token"] == "user_token"
    assert seen[0].url.params["access_token"] == f"{APP_ID}|fb_secret"


def test_verify_rejects_invalid_token(mock_graph):
    mock_graph(200, {"data": {"is_valid": False, "app_id": APP_ID}})
    with pytest.raises(MetaAPIError):
        _verify()


def test_verify_rejects_app_id_mismatch(mock_graph):
    mock_graph(200, {"data": {"is_valid": True, "app_id": "some_other_app"}})
    with pytest.raises(MetaAPIError):
        _verify()


def test_verify_rejects_missing_data(mock_graph):
    mock_graph(200, {})
    with pytest.raises(MetaAPIError):
        _verify()


def test_verify_raises_on_error_response(mock_graph):
    mock_graph(400, {"error": {"message": "Invalid OAuth access token.", "code": 190}})
    with pytest.raises(MetaAPIError, match="Invalid OAuth access token"):
        _verify()


def test_verify_raises_on_error_body_with_200(mock_graph):
    mock_graph(200, {"error": {"message": "boom"}})
    with pytest.raises(MetaAPIError, match="boom"):
        _verify()


def test_verify_raises_on_non_json_response(mock_graph):
    mock_graph(502, b"<html>bad gateway</html>")
    with pytest.raises(MetaAPIError):
        _verify()


@skip_if_no_db
def test_callback_stops_before_exchange_when_verification_fails(client, db_session: Session, monkeypatch):
    ws = Workspace(id=uuid4(), name="Default", slug="default")
    user = User(
        id=uuid4(),
        email="fb-verify-fail@test.com",
        name="fbverify",
        password_hash=hash_password("secret"),
        role="operator",
        is_active=True,
    )
    db_session.add_all([ws, user])
    db_session.flush()
    db_session.add(UserWorkspaceMembership(user_id=user.id, workspace_id=ws.id, role="owner"))
    db_session.commit()

    calls: list[str] = []

    async def failing_verify(token):
        calls.append("verify")
        raise MetaAPIError("Facebook access token is invalid or was not issued to this app")

    async def exchange(token):
        calls.append("exchange")
        return {"access_token": "long"}

    async def list_pages(token):
        calls.append("list_pages")
        return [{"id": "777", "name": "P", "access_token": "pt"}]

    async def subscribe(token, page_id):
        calls.append("subscribe")

    monkeypatch.setattr("app.api.routes_facebook.verify_user_access_token", failing_verify)
    monkeypatch.setattr("app.api.routes_facebook.exchange_for_long_lived_token", exchange)
    monkeypatch.setattr("app.api.routes_facebook.list_granted_pages", list_pages)
    monkeypatch.setattr("app.api.routes_facebook.subscribe_app_to_page", subscribe)

    state = "fb_verify_fail_state"
    Redis.from_url(settings.REDIS_URL, decode_responses=True).setex(f"facebook_oauth_state:{state}", 600, "1")

    login = client.post("/auth/login", data={"username": user.email, "password": "secret"})
    assert login.status_code == 200
    response = client.post(
        "/facebook/connect/callback",
        headers={"Authorization": f"Bearer {login.json()['access_token']}", "X-Workspace-Id": str(ws.id)},
        json={"access_token": "foreign_app_token", "state": state},
    )

    assert response.status_code == 502
    assert calls == ["verify"]  # exchange / list / subscribe never reached
    db_session.expire_all()
    assert db_session.query(FacebookPage).filter(FacebookPage.workspace_id == ws.id).count() == 0
