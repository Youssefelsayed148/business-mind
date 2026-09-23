"""Regression tests for workspace-scoped multi-tenancy (WhatsApp + Facebook).

Proves the fix for the cross-workspace data exposure: every
whatsapp/facebook route now resolves the caller's workspace from the
X-Workspace-Id header and the user_workspace_memberships table, and scopes
every query by workspace_id.

Covers:
- A user whose only membership is in a second workspace gets 404 from the
  get endpoints (not 403 — no existence leak) for resources belonging to the
  'default' workspace, and never sees them in the list endpoints.
- A user with no membership row for a workspace gets 403 from any
  workspace-scoped endpoint, including mutations.
- A missing or malformed X-Workspace-Id header is a 400.
- A user who IS a member of the 'default' workspace (i.e. what the 0017 data
  migration gives every pre-existing user) keeps full read access to that
  workspace's resources — the deploy must be a no-op behavior change.
"""

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.models.facebook_page import FacebookPage
from app.models.facebook_token import FacebookToken
from app.models.user import User
from app.models.user_workspace_membership import UserWorkspaceMembership
from app.models.whatsapp_account import WhatsappAccount
from app.models.whatsapp_token import WhatsappToken
from app.models.workspace import Workspace
from app.services.facebook_token_service import get_decrypted_token as get_fb_token
from app.services.whatsapp_token_service import get_decrypted_token as get_wa_token
from app.services.whatsapp_token_service import store_encrypted_token as store_wa_token
from app.services.facebook_token_service import store_encrypted_token as store_fb_token
from tests.conftest import skip_if_no_db


def _make_user(db_session: Session, email: str, role: str = "operator") -> User:
    user = User(
        id=uuid4(),
        email=email,
        name=email.split("@")[0],
        password_hash=hash_password("secret"),
        role=role,
        is_active=True,
    )
    db_session.add(user)
    return user


def _login(client: TestClient, email: str) -> str:
    response = client.post("/auth/login", data={"username": email, "password": "secret"})
    assert response.status_code == 200
    return response.json()["access_token"]


def _default_workspace(db_session: Session) -> Workspace:
    ws = Workspace(id=uuid4(), name="Default", slug="default")
    db_session.add(ws)
    return ws


def _auth_header(token: str, workspace_id: UUID | None) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    if workspace_id is not None:
        headers["X-Workspace-Id"] = str(workspace_id)
    return headers


def _seed_connect_state(redis_key: str) -> None:
    """Seed the Redis OAuth-state nonce the connect callbacks verify, exactly
    as /connect/start would (WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID /
    FACEBOOK_LOGIN_CONFIG_ID are unset locally, so /connect/start 503s).
    Pass the full key, e.g. 'whatsapp_oauth_state:<nonce>'."""
    from redis import Redis

    Redis.from_url(settings.REDIS_URL, decode_responses=True).setex(
        redis_key, 600, "1"
    )


@pytest.fixture
def two_workspaces(db_session: Session):
    """The 'default' workspace (holding the resources under test) plus a
    second workspace a rogue user belongs to."""
    ws_default = Workspace(id=uuid4(), name="Default", slug="default")
    ws_other = Workspace(id=uuid4(), name="Other Workspace", slug=f"other-{uuid4()}")
    db_session.add_all([ws_default, ws_other])
    db_session.commit()
    return ws_default, ws_other


@skip_if_no_db
def test_cross_workspace_user_gets_404_on_get_and_cannot_list(
    client: TestClient, db_session: Session, two_workspaces
):
    ws_default, ws_other = two_workspaces

    # A user whose ONLY membership is in the second workspace.
    intruder = _make_user(db_session, "intruder-ws@test.com")
    db_session.add(
        UserWorkspaceMembership(user_id=intruder.id, workspace_id=ws_other.id, role="owner")
    )

    # Resources belonging to the default workspace, invisible to the intruder.
    account = WhatsappAccount(
        id=uuid4(), workspace_id=ws_default.id, phone_number_id=str(uuid4())
    )
    page = FacebookPage(id=uuid4(), workspace_id=ws_default.id, page_id=str(uuid4()))
    db_session.add_all([account, page])
    db_session.commit()

    token = _login(client, "intruder-ws@test.com")
    headers = _auth_header(token, ws_other.id)

    # GET by id must 404 (not 403) — don't leak existence across workspaces.
    assert (
        client.get(f"/whatsapp/accounts/{account.id}", headers=headers).status_code == 404
    )
    assert (
        client.get(f"/facebook/accounts/{page.id}", headers=headers).status_code == 404
    )

    # The lists must not contain the other workspace's resources either.
    wa_list = client.get("/whatsapp/accounts", headers=headers)
    assert wa_list.status_code == 200
    assert all(item["id"] != str(account.id) for item in wa_list.json())

    fb_list = client.get("/facebook/accounts", headers=headers)
    assert fb_list.status_code == 200
    assert all(item["id"] != str(page.id) for item in fb_list.json())


@skip_if_no_db
def test_user_without_membership_gets_403(
    client: TestClient, db_session: Session, two_workspaces
):
    ws_default, _ = two_workspaces

    # An active user with NO membership rows at all.
    outsider = _make_user(db_session, "outsider-ws@test.com")
    db_session.commit()

    account = WhatsappAccount(
        id=uuid4(), workspace_id=ws_default.id, phone_number_id=str(uuid4())
    )
    db_session.add(account)
    db_session.commit()

    token = _login(client, "outsider-ws@test.com")
    headers = _auth_header(token, ws_default.id)

    # Reads and mutations alike must be rejected.
    assert client.get("/whatsapp/accounts", headers=headers).status_code == 403
    assert (
        client.get(f"/whatsapp/accounts/{account.id}", headers=headers).status_code == 403
    )
    assert client.get("/facebook/accounts", headers=headers).status_code == 403
    assert (
        client.patch(
            f"/whatsapp/accounts/{account.id}/ai-settings",
            headers=headers,
            json={"ai_enabled": True},
        ).status_code
        == 403
    )
    assert (
        client.delete(f"/facebook/accounts/{account.id}", headers=headers).status_code
        == 403
    )


@skip_if_no_db
def test_missing_or_malformed_workspace_header_gets_400(
    client: TestClient, db_session: Session, two_workspaces
):
    ws_default, ws_other = two_workspaces
    member = _make_user(db_session, "member-ws@test.com")
    db_session.add(
        UserWorkspaceMembership(user_id=member.id, workspace_id=ws_default.id, role="admin")
    )
    db_session.commit()

    token = _login(client, "member-ws@test.com")

    # No header at all.
    assert client.get("/whatsapp/accounts", headers=_auth_header(token, None)).status_code == 400
    # Not a valid UUID.
    assert (
        client.get(
            "/facebook/accounts", headers=_auth_header(token, "not-a-uuid")
        ).status_code
        == 400
    )


@skip_if_no_db
def test_default_workspace_member_keeps_access(
    client: TestClient, db_session: Session, two_workspaces
):
    """The 0017 data migration gives every pre-existing user a membership in
    the 'default' workspace carrying their users.role — access must be
    unchanged for them."""
    ws_default, _ = two_workspaces

    member = _make_user(db_session, "existing-admin@test.com", role="admin")
    db_session.add(
        UserWorkspaceMembership(user_id=member.id, workspace_id=ws_default.id, role="admin")
    )

    account = WhatsappAccount(
        id=uuid4(), workspace_id=ws_default.id, phone_number_id=str(uuid4())
    )
    page = FacebookPage(id=uuid4(), workspace_id=ws_default.id, page_id=str(uuid4()))
    db_session.add_all([account, page])
    db_session.commit()

    token = _login(client, "existing-admin@test.com")
    headers = _auth_header(token, ws_default.id)

    wa_list = client.get("/whatsapp/accounts", headers=headers)
    assert wa_list.status_code == 200
    assert any(item["id"] == str(account.id) for item in wa_list.json())

    assert (
        client.get(f"/whatsapp/accounts/{account.id}", headers=headers).status_code == 200
    )
    assert client.get(f"/facebook/accounts/{page.id}", headers=headers).status_code == 200

    # Mutations still work for a member with the manage_accounts permission.
    patched = client.patch(
        f"/whatsapp/accounts/{account.id}/ai-settings",
        headers=headers,
        json={"ai_enabled": True},
    )
    assert patched.status_code == 200
    assert patched.json()["ai_enabled"] is True


# --- Cross-workspace connect-flow conflicts (no silent re-pointing) ---------


@skip_if_no_db
def test_cross_workspace_whatsapp_reconnect_returns_409_and_leaves_row_untouched(
    client: TestClient,
    db_session: Session,
    two_workspaces,
    monkeypatch,
):
    """A WhatsApp number already connected to workspace A must NOT be
    silently re-pointed to workspace B when B's Embedded Signup posts the
    same phone_number_id: 409 before any mutation, and the original row's
    workspace_id + encrypted token must be completely unchanged."""
    from app.api.routes_whatsapp import (
        exchange_code_for_token,
        exchange_for_long_lived_token,
        fetch_phone_number_metadata,
        subscribe_app_to_waba,
    )

    ws_default, ws_other = two_workspaces

    intruder = _make_user(db_session, "wa-conflict@test.com")
    db_session.add(
        UserWorkspaceMembership(user_id=intruder.id, workspace_id=ws_other.id, role="owner")
    )
    account = WhatsappAccount(
        id=uuid4(),
        workspace_id=ws_default.id,
        phone_number_id="1008677222",
        display_phone_number="+15550001111",
        ai_enabled=True,
    )
    db_session.add(account)
    db_session.commit()
    store_wa_token(db_session, account.id, "original_wa_token")

    # Snapshot the row + its active encrypted token before the attempt.
    db_session.expire_all()
    original = (
        db_session.query(WhatsappAccount).filter(WhatsappAccount.id == account.id).first()
    )
    original_workspace_id = original.workspace_id
    original_display = original.display_phone_number
    original_ai_enabled = original.ai_enabled
    original_token = get_wa_token(db_session, account.id)
    original_token_rows = [
        t.access_token
        for t in db_session.query(WhatsappToken)
        .filter(WhatsappToken.whatsapp_account_id == account.id)
        .all()
    ]

    async def fake_exchange(code):
        return {"access_token": "short_lived_token"}

    async def fake_long_lived(short_token):
        return {"access_token": "brand_new_long_lived_token", "expires_in": 5184000}

    async def fake_subscribe(user_token, waba_id):
        return None

    async def fake_metadata(token, phone_number_id):
        return {"display_phone_number": "+15559997777"}

    monkeypatch.setattr("app.api.routes_whatsapp.exchange_code_for_token", fake_exchange)
    monkeypatch.setattr(
        "app.api.routes_whatsapp.exchange_for_long_lived_token", fake_long_lived
    )
    monkeypatch.setattr("app.api.routes_whatsapp.subscribe_app_to_waba", fake_subscribe)
    monkeypatch.setattr(
        "app.api.routes_whatsapp.fetch_phone_number_metadata", fake_metadata
    )

    state = "wa_conflict_state"
    _seed_connect_state(f"whatsapp_oauth_state:{state}")

    token = _login(client, "wa-conflict@test.com")
    response = client.post(
        "/whatsapp/connect/callback",
        headers=_auth_header(token, ws_other.id),
        json={
            "code": "some_code",
            "phone_number_id": "1008677222",
            "waba_id": "some_waba",
            "state": state,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "This WhatsApp number is already connected to a different workspace."
    )

    # The original row: still workspace A's, fields untouched, and the Meta
    # exchange never wrote through (no new token row, same ciphertext).
    db_session.expire_all()
    untouched = (
        db_session.query(WhatsappAccount).filter(WhatsappAccount.id == account.id).first()
    )
    assert untouched.workspace_id == original_workspace_id
    assert untouched.display_phone_number == original_display
    assert untouched.ai_enabled == original_ai_enabled
    assert get_wa_token(db_session, account.id) == original_token
    new_token_rows = [
        t.access_token
        for t in db_session.query(WhatsappToken)
        .filter(WhatsappToken.whatsapp_account_id == account.id)
        .all()
    ]
    assert new_token_rows == original_token_rows


@skip_if_no_db
def test_cross_workspace_facebook_reconnect_reports_conflict_and_leaves_row_untouched(
    client: TestClient,
    db_session: Session,
    two_workspaces,
    monkeypatch,
):
    """A Facebook Page already connected to workspace A must surface as a
    conflict (not a silent re-point) when workspace B's connect flow grants
    the same page_id, without aborting other pages in the batch. The
    original row's workspace_id + encrypted Page token must be unchanged."""
    ws_default, ws_other = two_workspaces

    intruder = _make_user(db_session, "fb-conflict@test.com")
    db_session.add(
        UserWorkspaceMembership(user_id=intruder.id, workspace_id=ws_other.id, role="owner")
    )
    page = FacebookPage(
        id=uuid4(),
        workspace_id=ws_default.id,
        page_id="111222333444555",
        page_name="Original Name",
        ai_enabled=True,
    )
    db_session.add(page)
    db_session.commit()
    store_fb_token(db_session, page.id, "original_page_token")

    db_session.expire_all()
    original_workspace_id = page.workspace_id
    original_name = page.page_name
    original_ai_enabled = page.ai_enabled
    original_token = get_fb_token(db_session, page.id)


    original_token_rows = [
        t.access_token
        for t in db_session.query(FacebookToken)
        .filter(FacebookToken.facebook_page_id == page.id)
        .all()
    ]

    async def fake_exchange(code):
        return {"access_token": "short_lived_token"}

    async def fake_long_lived(short_token):
        return {"access_token": "brand_new_long_lived_token"}

    async def fake_list_granted_pages(user_token):
        # Two pages granted: the conflicting one (workspace A's) and a brand
        # new one that should still connect successfully.
        return [
            {"id": "111222333444555", "name": "Rename Attempt", "access_token": "ptoken_conflict"},
            {"id": "999888777666000", "name": "Fresh Page", "access_token": "ptoken_fresh"},
        ]

    async def fake_subscribe(token, page_id):
        return None

    monkeypatch.setattr(
        "app.api.routes_facebook.exchange_code_for_token", fake_exchange
    )
    monkeypatch.setattr(
        "app.api.routes_facebook.exchange_for_long_lived_token", fake_long_lived
    )
    monkeypatch.setattr(
        "app.api.routes_facebook.list_granted_pages", fake_list_granted_pages
    )
    monkeypatch.setattr("app.api.routes_facebook.subscribe_app_to_page", fake_subscribe)

    state = "fb_conflict_state"
    _seed_connect_state(f"facebook_oauth_state:{state}")

    token = _login(client, "fb-conflict@test.com")
    response = client.post(
        "/facebook/connect/callback",
        headers=_auth_header(token, ws_other.id),
        json={"code": "some_code", "state": state},
    )

    assert response.status_code == 200
    body = response.json()
    # The conflicting page did not connect; the fresh one did.
    assert [c["page_id"] for c in body["connected"]] == ["999888777666000"]
    assert body["conflicts"] == [
        {
            "page_id": "111222333444555",
            "page_name": "Rename Attempt",
            "reason": "Already connected to a different workspace",
        }
    ]

    # The conflicting page row: still workspace A's, fields untouched, same
    # single encrypted token row.
    db_session.expire_all()
    untouched = (
        db_session.query(FacebookPage).filter(FacebookPage.id == page.id).first()
    )
    assert untouched.workspace_id == original_workspace_id
    assert untouched.page_name == original_name
    assert untouched.ai_enabled == original_ai_enabled
    assert get_fb_token(db_session, page.id) == original_token
    new_token_rows = [
        t.access_token
        for t in db_session.query(FacebookToken)
        .filter(FacebookToken.facebook_page_id == page.id)
        .all()
    ]
    assert new_token_rows == original_token_rows

    # The non-conflicting page connected normally into workspace B.
    fresh = (
        db_session.query(FacebookPage).filter(FacebookPage.page_id == "999888777666000").first()
    )
    assert fresh is not None
    assert fresh.workspace_id == ws_other.id
    assert fresh.status == "connected"
