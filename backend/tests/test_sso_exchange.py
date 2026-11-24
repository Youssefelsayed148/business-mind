"""POST /auth/sso/exchange end to end (flag off and on). Synthetic keys and data only."""
import base64
import json
import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.config import settings
from app.models.audit_log import AuditLog
from app.models.user import User
from app.models.user_workspace_membership import UserWorkspaceMembership
from app.models.workspace import Workspace

KID = "k1"
PRIVATE = Ed25519PrivateKey.generate()
PUBLIC_PEM = PRIVATE.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
URL = "/auth/sso/exchange"
GENERIC = {"detail": "Invalid assertion"}


class FakeRedis:
    def __init__(self):
        self.seen = set()

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.seen:
            return None
        self.seen.add(key)
        return True


class DownRedis:
    def set(self, *a, **k):
        raise RedisConnectionError("down")


@pytest.fixture
def sso_on(monkeypatch):
    import app.services.sso_assertion as mod

    store = FakeRedis()
    monkeypatch.setattr(settings, "SSO_ASSERTION_ENABLED", True)
    monkeypatch.setattr(settings, "SSO_PUBLIC_KEYS", json.dumps({KID: PUBLIC_PEM}))
    monkeypatch.setattr(mod, "_redis", lambda: store)
    return store


@pytest.fixture
def ws(db_session):
    row = Workspace(name="Synthetic", slug=uuid.uuid4().hex, saas_tenant_id=uuid.uuid4())
    db_session.add(row)
    db_session.flush()
    return row


def assertion(ws=None, **over):
    now = int(time.time())
    claims = {
        "iss": settings.SSO_ISSUER, "aud": settings.SSO_AUDIENCE, "sub": str(uuid.uuid4()),
        "jti": uuid.uuid4().hex, "iat": now, "nbf": now, "exp": now + 60, "email": "p@example.test",
        "scope": "client", "role": "admin", "locations": None, "via_agency": None, "mfa": True,
    }
    if ws is not None:
        claims.update(org=str(ws.saas_tenant_id), workspace=str(ws.id))
    claims.update(over)
    return jwt.encode({k: v for k, v in claims.items() if v is not ...}, PRIVATE, algorithm="EdDSA", headers={"kid": KID})


def audit_reasons(db, action):
    return [r.metadata_.get("reason") for r in db.query(AuditLog).filter_by(action=action).all()]


def test_flag_off_answers_like_an_unknown_route(client, ws, monkeypatch):
    monkeypatch.setattr(settings, "SSO_ASSERTION_ENABLED", False)
    unknown = client.post("/auth/does-not-exist", json={})
    for payload in ({"assertion": "x"}, {}, None):
        r = client.post(URL, json=payload) if payload is not None else client.post(URL, content=b"not json")
        assert (r.status_code, r.json()) == (unknown.status_code, unknown.json()) == (404, {"detail": "Not Found"})


def test_valid_exchange_issues_a_short_sso_token(client, db_session, sso_on, ws):
    r = client.post(URL, json={"assertion": assertion(ws, role="manager")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer" and body["scope"] == "client"
    assert body["expires_in"] == settings.SSO_TOKEN_MINUTES * 60 and body["workspace_id"] == str(ws.id)
    payload = jwt.decode(body["access_token"], settings.JWT_SECRET, algorithms=["HS256"])
    assert payload["type"] == "sso_access" and payload["scope"] == "client" and payload["ws"] == str(ws.id)
    assert 0 < payload["exp"] - time.time() <= settings.SSO_TOKEN_MINUTES * 60
    user = db_session.query(User).filter_by(id=payload["sub"]).one()
    assert user.auth_source == "sso" and user.role == "viewer"
    (m,) = db_session.query(UserWorkspaceMembership).filter_by(user_id=user.id).all()
    assert (m.workspace_id, m.role, m.source) == (ws.id, "operator", "sso")
    assert db_session.query(AuditLog).filter_by(action="sso_exchange_succeeded", actor_user_id=user.id).count() == 1


def test_staff_exchange(client, db_session, sso_on):
    r = client.post(URL, json={"assertion": assertion(scope="staff", role=...)})
    assert r.status_code == 200 and r.json()["scope"] == "staff" and r.json()["workspace_id"] is None


def test_replay_is_refused_and_audited(client, db_session, sso_on, ws):
    token = assertion(ws)
    assert client.post(URL, json={"assertion": token}).status_code == 200
    r = client.post(URL, json={"assertion": token})
    assert (r.status_code, r.json()) == (401, GENERIC)
    assert audit_reasons(db_session, "sso_exchange_failed") == ["replay"]


@pytest.mark.parametrize(
    "over,reason",
    [({"aud": "x"}, "bad_aud"), ({"iss": "x"}, "bad_iss"), ({"exp": 1, "iat": 0, "nbf": 0}, "expired")],
)
def test_bad_assertions_get_one_generic_answer(client, db_session, sso_on, ws, over, reason):
    r = client.post(URL, json={"assertion": assertion(ws, **over)})
    assert (r.status_code, r.json()) == (401, GENERIC)
    assert audit_reasons(db_session, "sso_exchange_failed") == [reason]
    assert db_session.query(User).filter_by(auth_source="sso").count() == 0


def test_tampered_and_garbage_are_refused(client, sso_on, ws):
    head, body, sig = assertion(ws).split(".")
    raw = bytearray(base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4)))
    raw[0] ^= 0x01  # always changes the signature, unlike overwriting characters
    flipped = base64.urlsafe_b64encode(bytes(raw)).rstrip(b"=").decode()
    assert flipped != sig
    for bad in (f"{head}.{body}.{flipped}", "not-a-jwt"):
        r = client.post(URL, json={"assertion": bad})
        assert (r.status_code, r.json()) == (401, GENERIC)


@pytest.mark.parametrize("raw", [b"", b"not json", b"[]", b'{"assertion": 5}', b'{"assertion": ""}', b'{"other": "x"}'])
def test_malformed_requests_are_400(client, sso_on, raw):
    r = client.post(URL, content=raw, headers={"content-type": "application/json"})
    assert r.status_code == 400


def test_oversized_assertion_is_400(client, sso_on):
    assert client.post(URL, json={"assertion": "a" * 5000}).status_code == 400


def test_redis_down_fails_closed(client, db_session, monkeypatch, sso_on, ws):
    import app.services.sso_assertion as mod

    monkeypatch.setattr(mod, "_redis", lambda: DownRedis())
    r = client.post(URL, json={"assertion": assertion(ws)})
    assert r.status_code == 503 and "access_token" not in r.json()
    assert audit_reasons(db_session, "sso_exchange_failed") == ["replay_store_unavailable"]
    assert db_session.query(User).filter_by(auth_source="sso").count() == 0


def test_workspace_mapping_mismatch_is_refused_and_leaves_no_rows(client, db_session, sso_on, ws):
    r = client.post(URL, json={"assertion": assertion(ws, org=str(uuid.uuid4()))})
    assert (r.status_code, r.json()) == (401, GENERIC)
    assert audit_reasons(db_session, "sso_exchange_failed") == ["workspace_mapping_mismatch"]
    assert db_session.query(User).filter_by(auth_source="sso").count() == 0


def test_deactivated_shadow_cannot_exchange(client, db_session, sso_on, ws):
    sub = str(uuid.uuid4())
    assert client.post(URL, json={"assertion": assertion(ws, sub=sub)}).status_code == 200
    db_session.query(User).filter_by(sso_subject=uuid.UUID(sub)).one().is_active = False
    db_session.flush()
    r = client.post(URL, json={"assertion": assertion(ws, sub=sub)})
    assert (r.status_code, r.json()) == (401, GENERIC)
    assert audit_reasons(db_session, "sso_exchange_failed")[-1] == "user_inactive"
