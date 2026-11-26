"""Login buckets, dummy hash, enumeration safety and login audit (design 6.6, 6.7, 10).

Synthetic data only."""

from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.identity.login as login_module
from app.auth.security import verify_password
from app.core.config import get_settings
from app.db.models import AuditEvent, User
from tests.conftest import build_test_settings
from tests.helpers import PASSWORD
from tests.identity_helpers import make_person
from tests.identity_settings import v2_settings


def attempt(app: FastAPI, email: str, password: str = PASSWORD, ip: str | None = None) -> Any:
    client = TestClient(app, raise_server_exceptions=False)
    headers = {"X-Forwarded-For": ip} if ip else {}
    return client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}, headers=headers
    )


def test_five_attempts_per_email_and_ip_then_a_hard_stop(v2_app: FastAPI, db: Session) -> None:
    v2_app.dependency_overrides[get_settings] = lambda: v2_settings()
    person = make_person(v2_app, "target", db=db)
    other = make_person(v2_app, "bystander", db=db)
    codes = [
        attempt(v2_app, person.email, "wrong-password", ip="203.0.113.7").status_code
        for _ in range(5)
    ]
    assert codes == [401] * 5
    # Even the right password is refused now: the bucket is full for this (email, IP).
    blocked = attempt(v2_app, person.email, ip="203.0.113.7")
    assert blocked.status_code == 429 and blocked.json()["error"]["code"] == "RATE_LIMITED"
    # The victim is not locked out: another IP and another email are unaffected.
    assert attempt(v2_app, person.email, ip="198.51.100.9").status_code == 200
    assert attempt(v2_app, other.email, ip="203.0.113.7").status_code == 200


def test_an_unknown_address_is_counted_exactly_like_a_known_one(
    v2_app: FastAPI, db: Session
) -> None:
    v2_app.dependency_overrides[get_settings] = lambda: v2_settings()
    ghost = f"ghost-{uuid4().hex[:8]}@example.com"
    codes = [attempt(v2_app, ghost, "x" * 12, ip="203.0.113.8").status_code for _ in range(7)]
    assert codes == [401] * 5 + [429] * 2


def test_the_per_email_bucket_only_slows_and_never_locks(
    v2_app: FastAPI, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    v2_app.dependency_overrides[get_settings] = lambda: v2_settings(
        login_email_attempts=2, login_email_ip_attempts=1000
    )
    delays: list[float] = []
    monkeypatch.setattr("app.identity.login.time.sleep", delays.append)
    person = make_person(v2_app, "spread", db=db)
    for index in range(4):  # a different IP each time: an attacker spreading out
        attempt(v2_app, person.email, "wrong-password", ip=f"203.0.113.{index + 20}")
    assert delays == [0.25, 0.5]
    assert attempt(v2_app, person.email, ip="203.0.113.99").status_code == 200  # never hard-locked
    assert delays[-1] == 0.75
    assert max(delays) <= login_module.MAX_SLOWDOWN_SECONDS


def test_unknown_and_wrong_password_look_identical_and_cost_one_hash_each(
    v2_app: FastAPI, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    v2_app.dependency_overrides[get_settings] = lambda: v2_settings()
    person = make_person(v2_app, "real", db=db)
    seen: list[str] = []
    real_verify = verify_password

    def spy(password: str, password_hash: str) -> bool:
        seen.append(password_hash)
        return real_verify(password, password_hash)

    monkeypatch.setattr("app.identity.login.verify_password", spy)
    wrong = attempt(v2_app, person.email, "wrong-password")
    unknown = attempt(v2_app, f"nobody-{uuid4().hex[:8]}@example.com", "wrong-password")
    assert (wrong.status_code, wrong.json()["error"]["code"], wrong.json()["error"]["message"]) == (
        unknown.status_code,
        unknown.json()["error"]["code"],
        unknown.json()["error"]["message"],
    )
    assert len(seen) == 2  # a full Argon2 verification ran in both cases
    assert seen[0].startswith("$argon2id$") and seen[1].startswith("$argon2id$")
    assert seen[1] == login_module._dummy_hash() and seen[0] != seen[1]


def test_inactive_and_membershipless_revoked_accounts_use_the_same_answer(
    v2_app: FastAPI, db: Session
) -> None:
    v2_app.dependency_overrides[get_settings] = lambda: v2_settings()
    person = make_person(v2_app, "gone", db=db)
    db.query(User).filter(User.id == person.user_id).update({"is_active": False})
    db.commit()
    inactive = attempt(v2_app, person.email)
    unknown = attempt(v2_app, f"nobody-{uuid4().hex[:8]}@example.com")
    assert inactive.status_code == unknown.status_code == 401
    assert inactive.json()["error"]["message"] == unknown.json()["error"]["message"]


def test_login_events_are_audited_without_secrets(v2_app: FastAPI, db: Session) -> None:
    v2_app.dependency_overrides[get_settings] = lambda: v2_settings()
    person = make_person(v2_app, "audited", db=db)
    attempt(v2_app, person.email, "wrong-password-123", ip="203.0.113.5")
    attempt(v2_app, f"nobody-{uuid4().hex[:8]}@example.com", "wrong-password-456", ip="203.0.113.5")
    attempt(v2_app, person.email, PASSWORD, ip="203.0.113.5")
    events = list(db.scalars(select(AuditEvent).where(AuditEvent.action.like("auth.login_%"))))
    by_action = sorted(e.action for e in events)
    assert by_action == ["auth.login_failed", "auth.login_failed", "auth.login_success"]
    failed_known = next(
        e for e in events if e.actor_user_id == person.user_id and e.action.endswith("failed")
    )
    assert failed_known.metadata_json["reason"] == "credentials"
    assert any(e.actor_user_id is None for e in events)  # the unknown address has no actor
    blob = str([e.metadata_json for e in events])
    assert "203.0.113.5" not in blob  # only a one-way digest of the address is kept
    assert "wrong-password" not in blob and PASSWORD not in blob and person.email not in blob
    db.expire_all()
    user = db.get(User, person.user_id)
    assert user is not None and user.last_login_at is not None


def test_flag_off_the_legacy_login_is_unchanged(app: FastAPI, db: Session) -> None:
    app.dependency_overrides[get_settings] = lambda: build_test_settings(
        login_rate_limit_attempts=1000
    )
    person = make_person(app, "legacy", db=db)
    # Six wrong attempts do not hit the new per-(email, IP) bucket when the flag is off.
    codes = [
        attempt(app, person.email, "wrong-password", ip="203.0.113.6").status_code for _ in range(6)
    ]
    assert codes == [401] * 6
    assert attempt(app, person.email, ip="203.0.113.6").status_code == 200
    assert not list(db.scalars(select(AuditEvent).where(AuditEvent.action.like("auth.login_%"))))
