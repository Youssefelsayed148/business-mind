"""With SSO_ASSERTION_ENABLED off the app must behave exactly as before, and legacy
tokens must behave identically whether the flag is off or on (identity design 9)."""
import uuid

import jwt
import pytest

from app.core.config import settings
from app.core.security import create_access_token, create_sso_access_token
from app.main import app
from app.models.user import User
from app.models.user_workspace_membership import UserWorkspaceMembership
from app.models.workspace import Workspace
from tests.route_inventory import concrete, inventory

ROUTES = [r for r in inventory(app) if r.path != "/auth/sso/exchange"]


@pytest.fixture
def world(db_session):
    ws = Workspace(name="Synthetic", slug=uuid.uuid4().hex)
    admin = User(email=f"{uuid.uuid4().hex}@example.test", password_hash="x", role="admin", is_active=True)
    viewer = User(email=f"{uuid.uuid4().hex}@example.test", password_hash="x", role="viewer", is_active=True)
    db_session.add_all([ws, admin, viewer])
    db_session.flush()
    db_session.add_all([
        UserWorkspaceMembership(user_id=admin.id, workspace_id=ws.id, role="owner"),
        UserWorkspaceMembership(user_id=viewer.id, workspace_id=ws.id, role="viewer"),
    ])
    db_session.flush()
    return ws, admin, viewer


def snapshot(client, headers):
    """(status, body) for every route, in route order."""
    out = []
    for r in ROUTES:
        resp = client.request(r.method, concrete(r.path), headers=headers)
        out.append((r.method, r.path, resp.status_code, resp.content))
    return out


def stable(rows):
    # concrete() draws fresh UUIDs per call, so bodies that echo the id differ by id only.
    return [(m, p, s) for m, p, s, _ in rows]


def test_legacy_credentials_behave_identically_flag_off_and_on(client, world, monkeypatch):
    ws, admin, viewer = world
    variants = {
        "no token": {},
        "garbage token": {"Authorization": "Bearer not-a-token"},
        "admin token": {"Authorization": f"Bearer {create_access_token(str(admin.id))}"},
        "viewer token + workspace": {
            "Authorization": f"Bearer {create_access_token(str(viewer.id))}", "X-Workspace-Id": str(ws.id)},
        "owner token + workspace": {
            "Authorization": f"Bearer {create_access_token(str(admin.id))}", "X-Workspace-Id": str(ws.id)},
    }
    for name, headers in variants.items():
        monkeypatch.setattr(settings, "SSO_ASSERTION_ENABLED", False)
        off = snapshot(client, headers)
        monkeypatch.setattr(settings, "SSO_ASSERTION_ENABLED", True)
        on = snapshot(client, headers)
        assert stable(off) == stable(on), name
        assert len(off) == len(ROUTES) > 100


def test_flag_off_new_route_is_404_and_sso_tokens_do_nothing(client, world, monkeypatch):
    ws, admin, viewer = world
    monkeypatch.setattr(settings, "SSO_ASSERTION_ENABLED", False)
    assert client.post("/auth/sso/exchange", json={"assertion": "x"}).status_code == 404
    garbage = {r.method + r.path: s for r, (_, _, s, _) in zip(ROUTES, snapshot(client, {"Authorization": "Bearer nope"}))}
    for scope in ("client", "staff"):
        token = create_sso_access_token(str(admin.id), scope)
        sso = {r.method + r.path: s for r, (_, _, s, _) in zip(ROUTES, snapshot(client, {"Authorization": f"Bearer {token}"}))}
        assert sso == garbage, scope


def test_login_still_issues_the_legacy_token_with_the_same_claims(client, db_session, monkeypatch):
    from app.core.security import hash_password

    email = f"{uuid.uuid4().hex}@example.test"
    db_session.add(User(email=email, password_hash=hash_password("synthetic-pass-1"), role="admin", is_active=True))
    db_session.flush()
    claim_sets = []
    for flag in (False, True):
        monkeypatch.setattr(settings, "SSO_ASSERTION_ENABLED", flag)
        resp = client.post("/auth/login", data={"username": email, "password": "synthetic-pass-1"})
        assert resp.status_code == 200 and resp.json()["token_type"] == "bearer"
        claim_sets.append(jwt.decode(resp.json()["access_token"], settings.JWT_SECRET, algorithms=["HS256"]))
        assert client.post("/auth/login", data={"username": email, "password": "wrong"}).status_code == 401
    assert [sorted(c) for c in claim_sets] == [["exp", "sub", "type"]] * 2
    assert [c["type"] for c in claim_sets] == ["access", "access"]
