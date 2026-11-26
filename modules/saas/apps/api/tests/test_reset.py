"""Self-service password reset (design 6.3, 10 T-RESET, T-ENUM). Synthetic data only."""

from datetime import timedelta
from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth.security import hash_token
from app.core.config import get_settings
from app.db.base import utcnow
from app.db.models import AuditEvent, User
from app.db.models.identity import PasswordResetToken
from app.identity.mailer import console_outbox
from app.identity.reset import REQUEST_MESSAGE
from tests.conftest import build_test_settings
from tests.helpers import PASSWORD
from tests.identity_helpers import make_person
from tests.identity_settings import v2_settings

NEW_PASSWORD = "An0ther-Str0ng!"


def request_reset(client: TestClient, email: str, **kwargs: Any) -> Any:
    return client.post("/api/v1/auth/password-reset/request", json={"email": email}, **kwargs)


def confirm(client: TestClient, token: str, password: str = NEW_PASSWORD) -> Any:
    return client.post(
        "/api/v1/auth/password-reset/confirm", json={"token": token, "new_password": password}
    )


def last_token_for(email: str) -> str:
    mail = [m for m in console_outbox() if m.to == email and m.kind == "password_reset"][-1]
    return mail.body.split("token=", 1)[1].strip()


def anonymous(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def test_the_request_answers_the_same_for_known_unknown_and_inactive(
    v2_app: FastAPI, db: Session
) -> None:
    v2_app.dependency_overrides[get_settings] = lambda: v2_settings()
    known = make_person(v2_app, "known", db=db)
    inactive = make_person(v2_app, "inactive", db=db)
    db.execute(update(User).where(User.id == inactive.user_id).values(is_active=False))
    db.commit()
    client = anonymous(v2_app)
    before = len(console_outbox())
    answers = [
        request_reset(client, email)
        for email in (known.email, f"nobody-{uuid4().hex[:8]}@example.com", inactive.email)
    ]
    assert {a.status_code for a in answers} == {202}
    assert {a.json()["message"] for a in answers} == {REQUEST_MESSAGE}
    assert all(set(a.json()) == {"message"} for a in answers)
    # Only the real, active account got an email.
    assert [m.to for m in list(console_outbox())[before:]] == [known.email]


def test_token_is_hashed_single_use_short_lived_and_audited(v2_app: FastAPI, db: Session) -> None:
    v2_app.dependency_overrides[get_settings] = lambda: v2_settings()
    person = make_person(v2_app, "victim", db=db)
    client = anonymous(v2_app)
    request_reset(client, person.email)
    token = last_token_for(person.email)
    row = db.scalar(select(PasswordResetToken).where(PasswordResetToken.user_id == person.user_id))
    assert row is not None and row.token_hash == hash_token(token) and token not in row.token_hash
    assert timedelta(minutes=29) < row.expires_at - utcnow() <= timedelta(minutes=30)
    done = confirm(client, token)
    assert done.status_code == 200
    again = confirm(client, token)
    assert again.status_code == 400 and again.json()["error"]["code"] == "INVALID_RESET_TOKEN"
    actions = set(
        db.scalars(select(AuditEvent.action).where(AuditEvent.actor_user_id == person.user_id))
    )
    assert {"auth.password_reset_requested", "auth.password_reset_completed"} <= actions
    metadata = str([e.metadata_json for e in db.scalars(select(AuditEvent))])
    assert token not in metadata and NEW_PASSWORD not in metadata


def test_confirming_sets_the_password_and_signs_everyone_out(v2_app: FastAPI, db: Session) -> None:
    v2_app.dependency_overrides[get_settings] = lambda: v2_settings()
    person = make_person(v2_app, "victim", db=db)
    assert person.client.get("/api/v1/auth/me").status_code == 200
    client = anonymous(v2_app)
    request_reset(client, person.email)
    assert confirm(client, last_token_for(person.email)).status_code == 200
    assert person.client.get("/api/v1/auth/me").status_code == 401  # the old session is dead
    fresh = anonymous(v2_app)
    old = fresh.post("/api/v1/auth/login", json={"email": person.email, "password": PASSWORD})
    assert old.status_code == 401
    new = fresh.post("/api/v1/auth/login", json={"email": person.email, "password": NEW_PASSWORD})
    assert new.status_code == 200


def test_a_newer_request_cancels_the_older_token(v2_app: FastAPI, db: Session) -> None:
    v2_app.dependency_overrides[get_settings] = lambda: v2_settings()
    person = make_person(v2_app, "twice", db=db)
    client = anonymous(v2_app)
    request_reset(client, person.email)
    first = last_token_for(person.email)
    request_reset(client, person.email)
    second = last_token_for(person.email)
    assert first != second
    assert confirm(client, first).status_code == 400
    assert confirm(client, second).status_code == 200


def test_expired_unknown_and_inactive_tokens_all_look_the_same(
    v2_app: FastAPI, db: Session
) -> None:
    v2_app.dependency_overrides[get_settings] = lambda: v2_settings()
    person = make_person(v2_app, "slow", db=db)
    client = anonymous(v2_app)
    request_reset(client, person.email)
    token = last_token_for(person.email)
    db.execute(update(PasswordResetToken).values(expires_at=utcnow() - timedelta(seconds=1)))
    db.commit()
    expired = confirm(client, token)
    unknown = confirm(client, "u" * 43)
    request_reset(client, person.email)
    fresh = last_token_for(person.email)
    db.execute(update(User).where(User.id == person.user_id).values(is_active=False))
    db.commit()
    inactive = confirm(client, fresh)
    bodies = {r.json()["error"]["message"] for r in (expired, unknown, inactive)}
    assert {r.status_code for r in (expired, unknown, inactive)} == {400} and len(bodies) == 1
    assert confirm(client, "u" * 43, "short").status_code == 422


def test_the_link_uses_the_configured_base_never_the_host_header(
    v2_app: FastAPI, db: Session
) -> None:
    v2_app.dependency_overrides[get_settings] = lambda: v2_settings(
        public_base_url="https://app.example.com"
    )
    person = make_person(v2_app, "poisoned", db=db)
    request_reset(
        anonymous(v2_app),
        person.email,
        headers={"Host": "evil.example.net", "X-Forwarded-Host": "evil.example.net"},
    )
    mail = [m for m in console_outbox() if m.to == person.email][-1]
    assert "https://app.example.com/reset-password?token=" in mail.body
    assert "evil.example.net" not in mail.body


def test_limits_never_change_the_answer(v2_app: FastAPI, db: Session) -> None:
    v2_app.dependency_overrides[get_settings] = lambda: v2_settings(reset_ip_attempts=6)
    person = make_person(v2_app, "flood", db=db)
    client = anonymous(v2_app)
    before = len(console_outbox())
    codes = [request_reset(client, person.email).status_code for _ in range(4)]
    assert codes == [202, 202, 202, 202]
    # Three emails per hour per address; the fourth request is answered but sends nothing.
    assert len(list(console_outbox())[before:]) == 3
    # The per-IP cap is the only thing that refuses, and it ignores which address was used.
    assert request_reset(client, "a@example.com").status_code == 202
    assert request_reset(client, "b@example.com").status_code == 202
    assert request_reset(client, "c@example.com").status_code == 429


def test_confirm_attempts_are_limited_per_ip(v2_app: FastAPI, db: Session) -> None:
    v2_app.dependency_overrides[get_settings] = lambda: v2_settings(reset_ip_attempts=3)
    client = anonymous(v2_app)
    codes = [confirm(client, f"{i:043d}").status_code for i in range(5)]
    assert codes == [400, 400, 400, 429, 429]


def test_flag_off_both_routes_answer_like_unknown_routes(app: FastAPI, db: Session) -> None:
    app.dependency_overrides[get_settings] = lambda: build_test_settings()
    client = anonymous(app)
    for response in (
        request_reset(client, "x@example.com"),
        confirm(client, "t" * 40),
    ):
        assert response.status_code == 404 and response.json() == {"detail": "Not Found"}
