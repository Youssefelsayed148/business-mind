"""Client-scope guard in get_current_user: every route is classified, client tokens are
denied everywhere outside the workspace-scoped allowlist (including all Instagram routes)."""
import uuid

import jwt
import pytest

from app.core.client_scope import CLIENT_SCOPED_EXACT_ROUTES, CLIENT_SCOPED_ROUTE_PREFIXES, client_scope_allows
from app.core.config import settings
from app.core.security import create_access_token, create_sso_access_token
from app.main import app
from app.models.user import User
from app.models.user_workspace_membership import UserWorkspaceMembership
from app.models.workspace import Workspace
from tests.route_inventory import concrete, inventory

GUARD_DETAIL = "This session cannot access this resource"
ROUTES = inventory(app)
USER_ROUTES = [r for r in ROUTES if r.uses_user]

# Routes that do not use get_current_user (public, signature-, state- or HMAC-authenticated).
# A new route that is neither here nor behind get_current_user fails the test: review it.
NOT_USER_AUTH = {
    ("GET", "/"), ("GET", "/health"), ("GET", "/webhooks/health"), ("GET", "/webhooks/meta"),
    ("POST", "/webhooks/meta"), ("POST", "/auth/login"), ("POST", "/auth/logout"),
    ("POST", "/auth/sso/exchange"), ("GET", "/docs"), ("GET", "/docs/oauth2-redirect"),
    ("GET", "/openapi.json"), ("GET", "/redoc"),
    ("GET", "/meta/connect/callback"), ("GET", "/meta/data-deletion/status/{code}"),
    ("POST", "/meta/compliance/{app}/data-deletion"), ("POST", "/meta/compliance/{app}/deauthorize"),
    ("POST", "/public/whatsapp/opt-in/{signed_token}"),
    ("GET", "/saas/connections/{connection_id}/health"), ("POST", "/saas/messages"),
    ("GET", "/api/saas/connections/{connection_id}/health"), ("POST", "/api/saas/messages"),
}
# Workspace-scoped through their own query filter rather than a membership dependency.
MEMBERSHIP_FILTERED = {"/auth/me", "/workspaces/me"}
DENIED_PREFIXES = ("/instagram", "/campaigns", "/conversations", "/messages", "/leads", "/logs", "/stats", "/meta")


def allowed(route) -> bool:
    return client_scope_allows(route.path, route.path)


@pytest.fixture
def sso_on(monkeypatch):
    monkeypatch.setattr(settings, "SSO_ASSERTION_ENABLED", True)


def make_user(db, role="viewer", **kw):
    user = User(email=f"{uuid.uuid4().hex}@example.test", password_hash="x", role=role, is_active=True,
                sso_subject=uuid.uuid4(), auth_source="sso", **kw)
    db.add(user)
    db.flush()
    return user


def make_workspace(db):
    ws = Workspace(name="Synthetic", slug=uuid.uuid4().hex, saas_tenant_id=uuid.uuid4())
    db.add(ws)
    db.flush()
    return ws


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


# --- classification ---------------------------------------------------------


def test_inventory_is_not_empty_and_sees_included_routers():
    paths = {r.path for r in ROUTES}
    assert len(ROUTES) > 100
    assert {"/instagram/accounts", "/whatsapp/accounts", "/facebook/accounts", "/auth/me"} <= paths


def test_every_route_is_classified():
    not_user = {(r.method, r.path) for r in ROUTES if not r.uses_user}
    assert not_user == NOT_USER_AUTH, (not_user - NOT_USER_AUTH, NOT_USER_AUTH - not_user)


def test_allowlist_contains_only_workspace_scoped_routes():
    for r in USER_ROUTES:
        if allowed(r):
            assert r.workspace_scoped or r.path in MEMBERSHIP_FILTERED, (r.method, r.path)


def test_allowlist_is_the_reviewed_constant():
    assert CLIENT_SCOPED_ROUTE_PREFIXES == ("/whatsapp", "/facebook", "/privacy/contact-erasure")
    assert CLIENT_SCOPED_EXACT_ROUTES == ("/auth/me", "/workspaces/me")


def test_instagram_and_other_global_routes_are_never_allowed():
    for r in USER_ROUTES:
        if r.path.startswith(DENIED_PREFIXES):
            assert not allowed(r), (r.method, r.path)
    assert sum(r.path.startswith("/instagram") for r in USER_ROUTES) >= 11


@pytest.mark.parametrize(
    "template,path,expected",
    [
        ("/whatsapp/accounts", "/whatsapp/accounts", True),
        ("/whatsapp", "/whatsapp", True),
        ("/auth/me", "/auth/me", True),
        ("/workspaces/me", "/workspaces/me", True),
        ("/whatsapp/accounts", "/instagram/accounts", False),  # template and path must agree
        ("/instagram/accounts", "/whatsapp/accounts", False),
        ("/whatsapp/accounts", None, False),
        (None, "/whatsapp/accounts", False),
        ("/whatsappx/accounts", "/whatsappx/accounts", False),
        ("/WhatsApp/accounts", "/WhatsApp/accounts", False),
        ("/auth/me/extra", "/auth/me/extra", False),
        ("/workspaces", "/workspaces", False),
        ("/workspaces/{workspace_id}", "/workspaces/abc", False),
        ("/workspaces/me/extra", "/workspaces/me/extra", False),
        ("/auth/login", "/auth/login", False),
        ("", "", False),
    ],
)
def test_matcher(template, path, expected):
    assert client_scope_allows(template, path) is expected


# --- live behavior on every user-authenticated route ----------------------------


@pytest.mark.parametrize("route", USER_ROUTES, ids=lambda r: f"{r.method} {r.path}")
def test_client_token_on_every_route(client, db_session, sso_on, route):
    user = make_user(db_session)
    token = create_sso_access_token(str(user.id), "client")
    resp = client.request(route.method, concrete(route.path), headers=bearer(token))
    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    detail = body.get("detail") if isinstance(body, dict) else None
    if allowed(route):
        assert detail != GUARD_DETAIL, (route.method, route.path)
    else:
        assert (resp.status_code, detail) == (403, GUARD_DETAIL), (route.method, route.path, resp.status_code)


def test_staff_token_is_not_guarded(client, db_session, sso_on):
    user = make_user(db_session, role="admin")
    headers = bearer(create_sso_access_token(str(user.id), "staff"))
    assert client.get("/instagram/accounts", headers=headers).status_code == 200
    assert client.get("/auth/me", headers=headers).status_code == 200


def test_client_token_reaches_only_its_workspace(client, db_session, sso_on):
    ws_a, ws_b = make_workspace(db_session), make_workspace(db_session)
    user = make_user(db_session)
    db_session.add(UserWorkspaceMembership(user_id=user.id, workspace_id=ws_a.id, role="viewer", source="sso"))
    db_session.flush()
    headers = bearer(create_sso_access_token(str(user.id), "client", str(ws_a.id)))
    mine = client.get("/workspaces/me", headers=headers)
    assert mine.status_code == 200 and [w["id"] for w in mine.json()] == [str(ws_a.id)]
    assert client.get("/whatsapp/accounts", headers={**headers, "X-Workspace-Id": str(ws_a.id)}).status_code == 200
    other = client.get("/whatsapp/accounts", headers={**headers, "X-Workspace-Id": str(ws_b.id)})
    assert other.status_code == 403 and other.json()["detail"] == "You do not have access to this workspace"
    assert client.get("/instagram/accounts", headers=headers).status_code == 403


# --- token handling -----------------------------------------------------------


def test_sso_token_is_rejected_when_the_flag_is_off(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "SSO_ASSERTION_ENABLED", False)
    user = make_user(db_session, role="admin")
    for scope in ("client", "staff"):
        r = client.get("/auth/me", headers=bearer(create_sso_access_token(str(user.id), scope)))
        assert (r.status_code, r.json()["detail"]) == (401, "Could not validate credentials")


def test_unknown_scope_type_and_inactive_user_are_rejected(client, db_session, sso_on):
    user = make_user(db_session, role="admin")

    def forge(**claims):
        base = {"sub": str(user.id), "exp": 4102444800, "type": "sso_access", "scope": "client"}
        return jwt.encode({**base, **claims}, settings.JWT_SECRET, algorithm="HS256")

    assert client.get("/auth/me", headers=bearer(forge(scope="root"))).status_code == 401
    assert client.get("/auth/me", headers=bearer(forge(scope=None))).status_code == 401
    assert client.get("/auth/me", headers=bearer(forge(type="refresh"))).status_code == 401
    assert client.get("/auth/me", headers=bearer(forge(type="whatever", scope="staff"))).status_code == 401
    assert client.get("/auth/me", headers=bearer(forge(sub=str(uuid.uuid4())))).status_code == 401
    user.is_active = False
    db_session.flush()
    assert client.get("/auth/me", headers=bearer(forge())).status_code == 401


def test_legacy_tokens_are_unaffected_by_scope_rules(client, db_session, sso_on):
    user = User(email=f"{uuid.uuid4().hex}@example.test", password_hash="x", role="admin", is_active=True)
    db_session.add(user)
    db_session.flush()
    headers = bearer(create_access_token(str(user.id)))
    assert client.get("/instagram/accounts", headers=headers).status_code == 200
    typeless = jwt.encode({"sub": str(user.id), "exp": 4102444800}, settings.JWT_SECRET, algorithm="HS256")
    assert client.get("/instagram/accounts", headers=bearer(typeless)).status_code == 200
