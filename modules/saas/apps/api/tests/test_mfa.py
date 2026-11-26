"""TOTP MFA (design 6.4): RFC 6238 vectors, enrollment, login, recovery, reset. Synthetic data only."""

import base64
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.channels.secrets import decrypt_secret
from app.core.config import get_settings
from app.db.base import utcnow
from app.db.models import AuditEvent, Membership, User
from app.db.models.identity import UserMfa, UserRecoveryCode
from app.db.session import session_factory
from app.identity import mfa
from tests.conftest import build_test_settings
from tests.helpers import PASSWORD, csrf_headers
from tests.identity_helpers import Person, build_org, join, make_person
from tests.identity_settings import MFA_KEY, v2_settings

# RFC 6238 appendix B, SHA-1 secret "12345678901234567890" (the 8-digit codes cut to 6).
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
RFC_VECTORS = {
    59: "287082",
    1111111109: "081804",
    1111111111: "050471",
    1234567890: "005924",
    2000000000: "279037",
    20000000000: "353130",
}


@pytest.mark.parametrize(("at", "expected"), sorted(RFC_VECTORS.items()))
def test_rfc_6238_vectors(at: int, expected: str) -> None:
    assert mfa.totp(RFC_SECRET, at) == expected


def test_drift_window_and_replay_rules() -> None:
    at = 1111111109
    step = at // 30
    assert mfa.match_totp(RFC_SECRET, mfa.totp(RFC_SECRET, at), at=at, last_used_step=None) == step
    for offset in (-1, 1):  # one step of drift either side is fine
        code = mfa.totp(RFC_SECRET, at + 30 * offset)
        assert mfa.match_totp(RFC_SECRET, code, at=at, last_used_step=None) == step + offset
    for offset in (-2, 2):
        code = mfa.totp(RFC_SECRET, at + 30 * offset)
        assert mfa.match_totp(RFC_SECRET, code, at=at, last_used_step=None) is None
    code = mfa.totp(RFC_SECRET, at)
    assert mfa.match_totp(RFC_SECRET, code, at=at, last_used_step=step) is None  # replay
    assert mfa.match_totp(RFC_SECRET, code, at=at, last_used_step=step - 1) == step
    for bad in ("", "12345", "1234567", "abcdef", "12 345", "287082 "):
        assert mfa.match_totp(RFC_SECRET, bad, at=59, last_used_step=None) in (None, 1)


def test_otpauth_uri_describes_the_standard_parameters() -> None:
    uri = mfa.otpauth_uri("who@example.com", RFC_SECRET)
    assert uri.startswith("otpauth://totp/Business%20Mind%3Awho%40example.com?")
    assert f"secret={RFC_SECRET}" in uri and "digits=6" in uri and "period=30" in uri


def _headers(person: Person) -> dict[str, str]:
    return csrf_headers(person.client)


def enroll(person: Person, db: Session) -> tuple[str, list[str]]:
    started = person.client.post("/api/v1/auth/mfa/enroll", headers=_headers(person))
    assert started.status_code == 200, started.text
    secret = started.json()["secret"]
    confirmed = person.client.post(
        "/api/v1/auth/mfa/confirm",
        json={"code": mfa.totp(secret, time.time())},
        headers=_headers(person),
    )
    assert confirmed.status_code == 200, confirmed.text
    return secret, confirmed.json()["recovery_codes"]


@pytest.fixture
def mfa_app(v2_app: FastAPI) -> FastAPI:
    v2_app.dependency_overrides[get_settings] = lambda: v2_settings()
    return v2_app


def test_enrollment_encrypts_the_secret_and_shows_recovery_codes_once(
    mfa_app: FastAPI, db: Session
) -> None:
    person = make_person(mfa_app, "enroll", db=db)
    assert person.client.get("/api/v1/auth/mfa").json() == {
        "enrolled": False,
        "pending": False,
        "recovery_codes_remaining": 0,
        "required": False,
        "available": True,
    }
    started = person.client.post("/api/v1/auth/mfa/enroll", headers=_headers(person)).json()
    assert person.client.get("/api/v1/auth/mfa").json()["pending"] is True
    row = db.get(UserMfa, person.user_id)
    assert row is not None and row.confirmed_at is None
    assert row.secret_ciphertext != started["secret"]
    assert decrypt_secret(row.secret_ciphertext, MFA_KEY) == started["secret"]
    wrong = person.client.post(
        "/api/v1/auth/mfa/confirm", json={"code": "000000"}, headers=_headers(person)
    )
    assert wrong.status_code == 400 and wrong.json()["error"]["code"] == "INVALID_MFA_CODE"
    right = person.client.post(
        "/api/v1/auth/mfa/confirm",
        json={"code": mfa.totp(started["secret"], time.time())},
        headers=_headers(person),
    )
    codes = right.json()["recovery_codes"]
    assert len(codes) == 10 and len(set(codes)) == 10
    assert all(re.fullmatch(r"[0-9a-f]{4}(-[0-9a-f]{4}){3}", c) for c in codes)
    stored = set(
        db.scalars(
            select(UserRecoveryCode.code_hash).where(UserRecoveryCode.user_id == person.user_id)
        )
    )
    assert len(stored) == 10 and not stored & set(codes)  # only hashes are kept
    db.expire_all()
    user = db.get(User, person.user_id)
    assert user is not None and user.mfa_enrolled_at is not None
    status = person.client.get("/api/v1/auth/mfa").json()
    assert status["enrolled"] is True and status["recovery_codes_remaining"] == 10
    again = person.client.post("/api/v1/auth/mfa/enroll", headers=_headers(person))
    assert again.status_code == 409
    actions = set(
        db.scalars(select(AuditEvent.action).where(AuditEvent.actor_user_id == person.user_id))
    )
    assert {"auth.mfa_failed", "auth.mfa_enrolled"} <= actions


def _fresh_login(app: FastAPI, person: Person, **extra: Any) -> Any:
    client = TestClient(app, raise_server_exceptions=False)
    return client.post(
        "/api/v1/auth/login", json={"email": person.email, "password": PASSWORD, **extra}
    )


def test_login_asks_for_the_code_only_after_the_password_was_right(
    mfa_app: FastAPI, db: Session
) -> None:
    mfa_app.dependency_overrides[get_settings] = lambda: v2_settings(
        mfa_verify_attempts=50, login_email_ip_attempts=50
    )
    person = make_person(mfa_app, "login", db=db)
    secret, _codes = enroll(person, db)
    wrong_password = TestClient(mfa_app, raise_server_exceptions=False).post(
        "/api/v1/auth/login", json={"email": person.email, "password": "nope-nope-nope"}
    )
    assert wrong_password.json()["error"]["code"] == "INVALID_CREDENTIALS"
    missing = _fresh_login(mfa_app, person)
    assert missing.status_code == 401 and missing.json()["error"]["code"] == "MFA_REQUIRED"
    bad = _fresh_login(mfa_app, person, mfa_code="000000")
    assert bad.status_code == 401 and bad.json()["error"]["code"] == "INVALID_MFA_CODE"
    # The enrollment code was just used in this 30 s step: it cannot be replayed.
    code = mfa.totp(secret, time.time())
    assert _fresh_login(mfa_app, person, mfa_code=code).status_code == 401
    db.execute(update(UserMfa).where(UserMfa.user_id == person.user_id).values(last_used_step=1))
    db.commit()
    ok = _fresh_login(mfa_app, person, mfa_code=code)
    assert ok.status_code == 200 and ok.json()["email"] == person.email
    replay = _fresh_login(mfa_app, person, mfa_code=code)
    assert replay.status_code == 401  # the same code never works twice


def test_a_recovery_code_works_once(mfa_app: FastAPI, db: Session) -> None:
    person = make_person(mfa_app, "recover", db=db)
    _secret, codes = enroll(person, db)
    assert _fresh_login(mfa_app, person, mfa_code=codes[0].upper()).status_code == 200
    assert _fresh_login(mfa_app, person, mfa_code=codes[0]).status_code == 401
    assert _fresh_login(mfa_app, person, mfa_code=codes[1].replace("-", "")).status_code == 200
    remaining = person.client.get("/api/v1/auth/mfa").json()["recovery_codes_remaining"]
    assert remaining == 8
    assert db.scalar(select(AuditEvent.id).where(AuditEvent.action == "auth.mfa_recovery_used"))


def test_verification_is_limited_per_user(mfa_app: FastAPI, db: Session) -> None:
    mfa_app.dependency_overrides[get_settings] = lambda: v2_settings(mfa_verify_attempts=3)
    person = make_person(mfa_app, "brute", db=db)
    enroll(person, db)  # the confirm call counted as the first attempt
    codes = [_fresh_login(mfa_app, person, mfa_code="000000").status_code for _ in range(3)]
    assert codes == [401, 401, 429]


def test_enrollment_is_unavailable_without_a_key(v2_app: FastAPI, db: Session) -> None:
    v2_app.dependency_overrides[get_settings] = lambda: v2_settings(mfa_secret_encryption_keys=None)
    person = make_person(v2_app, "nokey", db=db)
    response = person.client.post("/api/v1/auth/mfa/enroll", headers=_headers(person))
    assert response.status_code == 503 and response.json()["error"]["code"] == "MFA_UNAVAILABLE"
    assert person.client.get("/api/v1/auth/mfa").json()["available"] is False


def test_startup_refuses_enforcement_without_a_key() -> None:
    from app.core.config import validate_startup_settings

    with pytest.raises(RuntimeError):
        validate_startup_settings(
            build_test_settings(mfa_enforce_admins=True, mfa_secret_encryption_keys=None)
        )
    validate_startup_settings(v2_settings(mfa_enforce_admins=True, mfa_enforce_staff=True))


def test_required_flag_follows_enforcement_policy(mfa_app: FastAPI, db: Session) -> None:
    org = build_org(mfa_app, db, "Alpha")
    mfa_app.dependency_overrides[get_settings] = lambda: v2_settings(mfa_enforce_admins=True)
    owner = org.people["owner"]
    assert owner.client.get("/api/v1/auth/mfa").json()["required"] is False  # inside the grace
    db.execute(update(Membership).values(created_at=Membership.created_at - timedelta(days=15)))
    db.commit()
    assert owner.client.get("/api/v1/auth/mfa").json()["required"] is True
    assert org.people["manager"].client.get("/api/v1/auth/mfa").json()["required"] is False


def test_owner_resets_an_admins_mfa_but_not_an_owners_and_never_their_own(
    mfa_app: FastAPI, db: Session
) -> None:
    org = build_org(mfa_app, db, "Alpha")
    staff = make_person(mfa_app, "staff", staff=True, db=db)
    owner, admin, other = org.people["owner"], org.people["admin"], org.people["agent"]
    enroll(admin, db)
    enroll(owner, db)
    url = f"/api/v1/tenants/{org.tenant_id}/team/members/{{}}/mfa-reset"
    assert admin.client.post(url.format(other.user_id), headers=_headers(admin)).status_code == 403
    assert (
        owner.client.post(url.format(owner.user_id), headers=_headers(owner)).json()["error"][
            "code"
        ]
        == "SELF_EDIT"
    )
    assert admin.client.get("/api/v1/auth/mfa").json()["enrolled"] is True
    done = owner.client.post(url.format(admin.user_id), headers=_headers(owner))
    assert done.status_code == 204
    db.expire_all()
    user = db.get(User, admin.user_id)
    assert user is not None and user.mfa_enrolled_at is None
    assert db.get(UserMfa, admin.user_id) is None
    assert not db.scalars(
        select(UserRecoveryCode).where(UserRecoveryCode.user_id == admin.user_id)
    ).all()
    assert admin.client.get("/api/v1/auth/me").status_code == 401  # signed out
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "auth.mfa_reset"))
    assert event is not None and event.actor_user_id == owner.user_id
    assert event.metadata_json == {"target_role": "admin"}
    # An Owner's MFA is reset by staff only.
    second_owner = make_person(mfa_app, "owner2", db=db)
    join(db, org.tenant_id, second_owner.user_id, "owner")
    assert (
        owner.client.post(url.format(second_owner.user_id), headers=_headers(owner)).json()[
            "error"
        ]["code"]
        == "STAFF_REQUIRED"
    )
    assert staff.client.post(url.format(owner.user_id), headers=_headers(staff)).status_code == 204


def test_flag_off_mfa_routes_are_404_and_login_ignores_the_code(app: FastAPI, db: Session) -> None:
    app.dependency_overrides[get_settings] = lambda: build_test_settings()
    person = make_person(app, "legacy", db=db)
    db.execute(update(User).where(User.id == person.user_id).values(mfa_enrolled_at=utcnow()))
    db.commit()
    assert person.client.get("/api/v1/auth/mfa").json() == {"detail": "Not Found"}
    assert (
        person.client.post("/api/v1/auth/mfa/enroll", headers=_headers(person)).status_code == 404
    )
    legacy = _fresh_login(app, person)
    assert legacy.status_code == 200  # no second factor is asked for while the flag is off
    assert _fresh_login(app, person, mfa_code="123456").status_code == 200


# --- Phase 4A, review item 1: two requests must not both spend the same code -------------------


def _race(engine: Engine, user_id: Any, code: str, workers: int = 4) -> list[bool]:
    """Verify one code from several sessions at the same moment; return each outcome."""
    settings = v2_settings(mfa_verify_attempts=100)
    barrier = threading.Barrier(workers)

    def attempt() -> bool:
        session = session_factory(engine)()
        try:
            user = session.get(User, user_id)
            barrier.wait()
            return mfa.verify_second_factor(session, settings, user, code)
        finally:
            session.close()

    with ThreadPoolExecutor(workers) as pool:
        return [future.result() for future in [pool.submit(attempt) for _ in range(workers)]]


def test_a_recovery_code_cannot_be_spent_twice_at_once(
    mfa_app: FastAPI, db: Session, engine: Engine
) -> None:
    person = make_person(mfa_app, "race-recovery", db=db)
    _secret, codes = enroll(person, db)
    user_id = db.scalar(select(User.id).where(User.email == person.email))
    for code in codes[:5]:
        assert _race(engine, user_id, code).count(True) == 1


def test_a_totp_code_cannot_be_used_twice_at_once(
    mfa_app: FastAPI, db: Session, engine: Engine
) -> None:
    person = make_person(mfa_app, "race-totp", db=db)
    secret, _codes = enroll(person, db)
    user_id = db.scalar(select(User.id).where(User.email == person.email))
    for _ in range(5):
        db.execute(update(UserMfa).where(UserMfa.user_id == user_id).values(last_used_step=None))
        db.commit()
        assert _race(engine, user_id, mfa.totp(secret, time.time())).count(True) == 1
