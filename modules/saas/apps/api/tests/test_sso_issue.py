"""SSO issuing (design 2): claims, refusals, redirect allowlist, flag off. Synthetic data only."""

import base64
import json
import re
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import UUID, uuid4

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings, validate_startup_settings
from app.db.base import utcnow
from app.db.models import AgencyGrant, AuditEvent, Membership, Tenant, User
from app.identity import agency as svc
from tests.conftest import build_test_settings
from tests.helpers import csrf_headers
from tests.identity_helpers import ROLES, Person, build_org, join, make_person, make_tenant
from tests.test_agency_grants import _ctx, _setup, _user

KID = "test-kid-1"
CALLBACK = "https://many.example.com/sso/callback"
STATE = "s" * 24

_KEY = Ed25519PrivateKey.generate()
PRIVATE_PEM = _KEY.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
PUBLIC_KEY: Ed25519PublicKey = _KEY.public_key()
PUBLIC_PEM = PUBLIC_KEY.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()


def sso_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "sso_issuer_enabled": True,
        "sso_signing_kid": KID,
        "sso_signing_key_pem": SecretStr(PRIVATE_PEM),
        "sso_return_allowlist": [CALLBACK],
    }
    values.update(overrides)
    return build_test_settings(**values)


@pytest.fixture
def sso_app(app: FastAPI) -> FastAPI:
    app.dependency_overrides[get_settings] = lambda: sso_settings()
    return app


def _b64d(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def decode(token: str, *, verify: bool = True) -> tuple[dict[str, Any], dict[str, Any]]:
    head, body, sig = token.split(".")
    if verify:
        PUBLIC_KEY.verify(_b64d(sig), f"{head}.{body}".encode("ascii"))
    return json.loads(_b64d(head)), json.loads(_b64d(body))


def _map_workspace(db: Session, tenant_id: UUID) -> UUID:
    workspace = uuid4()
    db.execute(update(Tenant).where(Tenant.id == tenant_id).values(many_workspace_id=workspace))
    db.commit()
    return workspace


def _mint(person: Person, org: UUID | None, scope: str = "client") -> Any:
    body: dict[str, Any] = {"scope": scope}
    if org is not None:
        body["org"] = str(org)
    return person.client.post(
        "/api/v1/sso/assertions", json=body, headers=csrf_headers(person.client)
    )


def test_claims_signature_and_lifetime_for_every_role(sso_app: FastAPI, db: Session) -> None:
    org = build_org(sso_app, db, "Alpha")
    workspace = _map_workspace(db, org.tenant_id)
    seen: set[str] = set()
    for role in ROLES:
        person = org.people[role]
        response = _mint(person, org.tenant_id)
        assert response.status_code == 200, (role, response.text)
        payload = response.json()
        header, claims = decode(payload["assertion"])
        assert header == {"alg": "EdDSA", "typ": "JWT", "kid": KID}
        assert claims["iss"] == "business-mind-saas" and claims["aud"] == "many-api"
        assert claims["sub"] == str(person.user_id)
        assert claims["scope"] == "client" and claims["role"] == role
        assert claims["org"] == str(org.tenant_id) and claims["workspace"] == str(workspace)
        assert claims["locations"] is None and claims["via_agency"] is None
        assert claims["mfa"] is False and claims["email"] == person.email.lower()
        assert claims["exp"] - claims["iat"] == 60 and claims["nbf"] == claims["iat"]
        assert re.fullmatch(r"[0-9a-f]{32}", claims["jti"])
        assert claims["jti"] not in seen
        seen.add(claims["jti"])
        assert re.fullmatch(r"[0-9a-f]{16}", claims["sid"])
        assert payload["expires_in"] == 60 and payload["workspace_id"] == str(workspace)


def test_tampered_or_foreign_signature_never_verifies(sso_app: FastAPI, db: Session) -> None:
    org = build_org(sso_app, db, "Alpha")
    _map_workspace(db, org.tenant_id)
    token = _mint(org.people["owner"], org.tenant_id).json()["assertion"]
    head, body, sig = token.split(".")
    forged = json.loads(_b64d(body))
    forged["role"] = "owner"
    forged["sub"] = str(uuid4())
    new_body = base64.urlsafe_b64encode(json.dumps(forged).encode()).rstrip(b"=").decode()
    with pytest.raises(InvalidSignature):
        decode(f"{head}.{new_body}.{sig}")
    other = Ed25519PrivateKey.generate().sign(f"{head}.{body}".encode("ascii"))
    other_sig = base64.urlsafe_b64encode(other).rstrip(b"=").decode()
    with pytest.raises(InvalidSignature):
        decode(f"{head}.{body}.{other_sig}")


def test_mfa_claim_follows_the_enrolled_state(sso_app: FastAPI, db: Session) -> None:
    org = build_org(sso_app, db, "Alpha")
    _map_workspace(db, org.tenant_id)
    owner = org.people["owner"]
    db.execute(update(User).where(User.id == owner.user_id).values(mfa_enrolled_at=utcnow()))
    db.commit()
    assert decode(_mint(owner, org.tenant_id).json()["assertion"])[1]["mfa"] is True
    assert decode(_mint(org.people["admin"], org.tenant_id).json()["assertion"])[1]["mfa"] is False


def test_non_members_unmapped_and_unknown_organizations_get_404(
    sso_app: FastAPI, db: Session
) -> None:
    alpha = build_org(sso_app, db, "Alpha")
    beta = build_org(sso_app, db, "Beta")
    _map_workspace(db, alpha.tenant_id)
    # Beta is not mapped to a Many workspace yet.
    assert _mint(beta.people["owner"], beta.tenant_id).status_code == 404
    assert _mint(beta.people["owner"], alpha.tenant_id).status_code == 404  # not a member of Alpha
    assert _mint(alpha.people["owner"], uuid4()).status_code == 404
    assert _mint(alpha.people["owner"], None).status_code == 422
    # A revoked membership is not a membership.
    db.execute(
        update(Membership)
        .where(
            Membership.tenant_id == alpha.tenant_id,
            Membership.user_id == alpha.people["agent"].user_id,
        )
        .values(status="revoked")
    )
    db.commit()
    assert _mint(alpha.people["agent"], alpha.tenant_id).status_code == 404
    assert (
        db.scalar(select(AuditEvent.id).where(AuditEvent.action == "sso.assertion_minted")) is None
    )


def test_location_limited_members_are_refused(sso_app: FastAPI, db: Session) -> None:
    tenant_id = make_tenant(db, "Limited")
    workspace = _map_workspace(db, tenant_id)
    person = make_person(sso_app, "limited", db=db)
    join(db, tenant_id, person.user_id, "agent", location_scope="limited")
    response = _mint(person, tenant_id)
    assert (
        response.status_code == 403
        and response.json()["error"]["code"] == "LOCATION_SCOPE_UNSUPPORTED"
    )
    assert workspace is not None


def test_staff_scope_needs_a_staff_user_and_staff_do_not_enter_client_scope(
    sso_app: FastAPI, db: Session
) -> None:
    org = build_org(sso_app, db, "Alpha")
    _map_workspace(db, org.tenant_id)
    staff = make_person(sso_app, "staff", staff=True, db=db)
    ok = _mint(staff, None, scope="staff")
    assert ok.status_code == 200
    _, claims = decode(ok.json()["assertion"])
    assert claims["scope"] == "staff" and "org" not in claims and "role" not in claims
    assert ok.json()["workspace_id"] is None
    assert _mint(org.people["owner"], None, scope="staff").status_code == 403
    # Staff without a real membership use the staff scope, not a client assertion.
    assert _mint(staff, org.tenant_id).status_code == 404


def test_agency_assertion_carries_cap_and_agency_and_dies_with_the_grant(
    sso_app: FastAPI, db: Session
) -> None:
    s = _setup(sso_app, db)
    _map_workspace(db, s.tenant_id)
    assert _mint(s.agent, s.tenant_id).status_code == 404  # no grant yet
    grant = s.grant(cap="manager")
    claims = decode(_mint(s.agent, s.tenant_id).json()["assertion"])[1]
    assert claims["role"] == "manager" and claims["via_agency"] == str(s.agency.id)
    # Expired grant: refused at mint (expiry is checked on every call).
    db.execute(
        update(AgencyGrant)
        .where(AgencyGrant.id == grant.id)
        .values(expires_at=utcnow() - timedelta(minutes=1))
    )
    db.commit()
    assert _mint(s.agent, s.tenant_id).status_code == 404
    db.execute(update(AgencyGrant).where(AgencyGrant.id == grant.id).values(expires_at=None))
    db.commit()
    assert _mint(s.agent, s.tenant_id).status_code == 200
    svc.revoke_grant(_ctx(db, s.tenant_id, s.owner), grant_id=grant.id)
    db.commit()
    assert _mint(s.agent, s.tenant_id).status_code == 404
    assert _user(db, s.agent) is not None


def test_unassigned_agency_person_and_other_clients_are_refused(
    sso_app: FastAPI, db: Session
) -> None:
    s = _setup(sso_app, db)
    other = build_org(sso_app, db, "Elsewhere")
    _map_workspace(db, s.tenant_id)
    _map_workspace(db, other.tenant_id)
    s.grant(cap="viewer")
    assert _mint(s.agent, other.tenant_id).status_code == 404  # grant is for another client
    assert _mint(s.stranger, s.tenant_id).status_code == 404  # not in the agency


def test_mfa_enforcement_for_staff_and_after_the_admin_grace(sso_app: FastAPI, db: Session) -> None:
    org = build_org(sso_app, db, "Alpha")
    _map_workspace(db, org.tenant_id)
    staff = make_person(sso_app, "staff", staff=True, db=db)
    sso_app.dependency_overrides[get_settings] = lambda: sso_settings(
        mfa_enforce_staff=True, mfa_enforce_admins=True
    )
    refused = _mint(staff, None, scope="staff")
    assert (
        refused.status_code == 403 and refused.json()["error"]["code"] == "MFA_ENROLLMENT_REQUIRED"
    )
    # Inside the 14-day grace a new Owner/Admin still gets in; Managers are never enforced.
    assert _mint(org.people["owner"], org.tenant_id).status_code == 200
    db.execute(update(Membership).values(created_at=utcnow() - timedelta(days=15)))
    db.commit()
    assert _mint(org.people["owner"], org.tenant_id).status_code == 403
    assert _mint(org.people["admin"], org.tenant_id).status_code == 403
    assert _mint(org.people["manager"], org.tenant_id).status_code == 200
    db.execute(
        update(User)
        .where(User.id.in_([staff.user_id, org.people["owner"].user_id]))
        .values(mfa_enrolled_at=utcnow())
    )
    db.commit()
    assert _mint(staff, None, scope="staff").status_code == 200
    assert _mint(org.people["owner"], org.tenant_id).status_code == 200


def test_mint_is_audited_without_the_token_and_rate_limited(sso_app: FastAPI, db: Session) -> None:
    org = build_org(sso_app, db, "Alpha")
    _map_workspace(db, org.tenant_id)
    sso_app.dependency_overrides[get_settings] = lambda: sso_settings(
        sso_mint_rate_limit_attempts=2
    )
    owner = org.people["owner"]
    token = _mint(owner, org.tenant_id).json()["assertion"]
    assert _mint(owner, org.tenant_id).status_code == 200
    assert _mint(owner, org.tenant_id).status_code == 429
    events = db.scalars(select(AuditEvent).where(AuditEvent.action == "sso.assertion_minted")).all()
    assert len(events) == 2 and all(e.tenant_id == org.tenant_id for e in events)
    assert events[0].actor_user_id == owner.user_id
    assert token not in json.dumps([e.metadata_json for e in events])


def test_post_needs_csrf_and_a_session(sso_app: FastAPI, db: Session) -> None:
    org = build_org(sso_app, db, "Alpha")
    _map_workspace(db, org.tenant_id)
    owner = org.people["owner"]
    no_csrf = owner.client.post("/api/v1/sso/assertions", json={"org": str(org.tenant_id)})
    assert no_csrf.status_code == 403
    anonymous = TestClient(sso_app, raise_server_exceptions=False)
    assert anonymous.post("/api/v1/sso/assertions", json={}).status_code in (401, 403)
    assert (
        anonymous.get(
            "/api/v1/sso/authorize",
            params={"state": STATE, "return": CALLBACK, "org": str(org.tenant_id)},
        ).status_code
        == 401
    )


def test_authorize_redirects_with_the_assertion_in_the_fragment(
    sso_app: FastAPI, db: Session
) -> None:
    org = build_org(sso_app, db, "Alpha")
    _map_workspace(db, org.tenant_id)
    owner = org.people["owner"]
    response = owner.client.get(
        "/api/v1/sso/authorize",
        params={"org": str(org.tenant_id), "state": STATE, "return": CALLBACK},
        follow_redirects=False,
    )
    assert response.status_code == 303
    parts = urlsplit(response.headers["location"])
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == CALLBACK and parts.query == ""
    fragment = parse_qs(parts.fragment)
    assert fragment["state"] == [STATE]
    claims = decode(unquote(fragment["assertion"][0]))[1]
    assert claims["role"] == "owner"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"


@pytest.mark.parametrize(
    "bad_return",
    [
        "https://evil.example.net/sso/callback",
        "https://many.example.com/sso/callback/extra",
        "https://many.example.com/sso/callbac",
        "https://MANY.example.com/sso/callback",
        "https://many.example.com@evil.example.net/sso/callback",
        "https://many.example.com.evil.example.net/sso/callback",
        "https://many.example.com/sso/callback?next=https://evil.example.net",
        "//evil.example.net/sso/callback",
        "http://many.example.com/sso/callback",
        "/sso/callback",
        "javascript:alert(1)",
        "",
    ],
)
def test_authorize_refuses_every_return_that_is_not_allowlisted_exactly(
    sso_app: FastAPI, db: Session, bad_return: str
) -> None:
    org = build_org(sso_app, db, "Alpha")
    _map_workspace(db, org.tenant_id)
    response = org.people["owner"].client.get(
        "/api/v1/sso/authorize",
        params={"org": str(org.tenant_id), "state": STATE, "return": bad_return},
        follow_redirects=False,
    )
    assert response.status_code == 422 and "location" not in response.headers


@pytest.mark.parametrize(
    "bad_state", ["short", "x" * 129, "has space in it......", "semi;colon;;;;;;;;;;;;;", ""]
)
def test_authorize_requires_a_well_formed_state(
    sso_app: FastAPI, db: Session, bad_state: str
) -> None:
    org = build_org(sso_app, db, "Alpha")
    _map_workspace(db, org.tenant_id)
    response = org.people["owner"].client.get(
        "/api/v1/sso/authorize",
        params={"org": str(org.tenant_id), "state": bad_state, "return": CALLBACK},
        follow_redirects=False,
    )
    assert response.status_code == 422


def test_flag_off_answers_like_an_unknown_route_for_everyone(app: FastAPI, db: Session) -> None:
    app.dependency_overrides[get_settings] = lambda: build_test_settings()
    org = build_org(app, db, "Alpha")
    owner = org.people["owner"]
    unknown = owner.client.get("/api/v1/sso/not-a-route")
    assert unknown.status_code == 404
    anonymous = TestClient(app, raise_server_exceptions=False)
    for client, headers in ((owner.client, csrf_headers(owner.client)), (anonymous, {})):
        post = client.post(
            "/api/v1/sso/assertions", json={"org": str(org.tenant_id)}, headers=headers
        )
        get = client.get("/api/v1/sso/authorize", params={"state": STATE, "return": CALLBACK})
        assert post.status_code == get.status_code == 404
        assert post.json() == get.json() == unknown.json() == {"detail": "Not Found"}


def test_startup_refuses_an_unusable_signing_key(db: Session) -> None:
    good = sso_settings()
    validate_startup_settings(good)
    for key, kid in (
        (None, KID),
        ("not a pem", KID),
        (PRIVATE_PEM, ""),
        (
            rsa.generate_private_key(65537, 2048)
            .private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
            .decode(),
            KID,
        ),
    ):
        secret = None if key is None else SecretStr(key)
        with pytest.raises(RuntimeError) as error:
            validate_startup_settings(sso_settings(sso_signing_key_pem=secret, sso_signing_kid=kid))
        assert "BEGIN" not in str(error.value) and PRIVATE_PEM not in str(error.value)
    # Flag off: the key is not even looked at.
    validate_startup_settings(build_test_settings(sso_signing_key_pem=None))
