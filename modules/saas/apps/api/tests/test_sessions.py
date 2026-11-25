"""Session policy (design 6.5): idle and absolute expiry, device list, log out everywhere.

Synthetic data only."""

from datetime import timedelta
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session as OrmSession

from app.core.config import get_settings
from app.db.base import utcnow
from app.db.models import AuditEvent, Session
from tests.conftest import build_test_settings
from tests.helpers import PASSWORD, csrf_headers
from tests.identity_helpers import Person, make_person
from tests.identity_settings import v2_settings


def age(db: OrmSession, user_id: Any, *, seen: timedelta, created: timedelta | None = None) -> None:
    values: dict[str, Any] = {"last_seen_at": utcnow() - seen}
    if created is not None:
        values["created_at"] = utcnow() - created
    db.execute(update(Session).where(Session.user_id == user_id).values(**values))
    db.commit()


def login(app: FastAPI, person: Person, **headers: str) -> TestClient:
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post(
        "/api/v1/auth/login", json={"email": person.email, "password": PASSWORD}, headers=headers
    )
    assert response.status_code == 200, response.text
    return client


def test_login_records_device_metadata_without_the_raw_address(
    v2_app: FastAPI, db: OrmSession
) -> None:
    v2_app.dependency_overrides[get_settings] = lambda: v2_settings()
    person = make_person(v2_app, "device", db=db)
    login(
        v2_app, person, **{"User-Agent": "Synthetic-Browser/1.0", "X-Forwarded-For": "203.0.113.4"}
    )
    row = db.scalar(select(Session).where(Session.user_agent.is_not(None)))
    assert row is not None and row.user_agent == "Synthetic-Browser/1.0"
    assert row.last_seen_at is not None
    assert row.ip_hash is not None and "203.0.113.4" not in row.ip_hash and len(row.ip_hash) == 16


def test_client_idle_timeout_and_touch(v2_app: FastAPI, db: OrmSession) -> None:
    v2_app.dependency_overrides[get_settings] = lambda: v2_settings()
    person = make_person(v2_app, "idle", db=db)
    client = login(v2_app, person)
    age(db, person.user_id, seen=timedelta(hours=11))
    assert client.get("/api/v1/auth/me").status_code == 200  # inside 12 h
    db.expire_all()
    touched = db.scalar(
        select(func.max(Session.last_seen_at)).where(
            Session.user_id == person.user_id, Session.revoked_at.is_(None)
        )
    )
    assert touched is not None and utcnow() - touched < timedelta(minutes=1)
    age(db, person.user_id, seen=timedelta(hours=13))
    expired = client.get("/api/v1/auth/me")
    assert expired.status_code == 401 and expired.json()["error"]["code"] == "SESSION_INVALID"
    db.expire_all()
    assert (
        db.scalar(select(func.max(Session.revoked_at)).where(Session.user_id == person.user_id))
        is not None
    )


def test_last_seen_is_refreshed_at_most_once_a_minute(v2_app: FastAPI, db: OrmSession) -> None:
    v2_app.dependency_overrides[get_settings] = lambda: v2_settings()
    person = make_person(v2_app, "touch", db=db)
    client = login(v2_app, person)
    recent = utcnow() - timedelta(seconds=20)
    db.execute(update(Session).where(Session.user_id == person.user_id).values(last_seen_at=recent))
    db.commit()
    assert client.get("/api/v1/auth/me").status_code == 200
    db.expire_all()
    seen = db.scalar(
        select(Session.last_seen_at).where(
            Session.user_id == person.user_id, Session.revoked_at.is_(None)
        )
    )
    assert seen == recent  # not touched: it was updated less than a minute ago


def test_staff_idle_is_thirty_minutes_and_absolute_twelve_hours(
    v2_app: FastAPI, db: OrmSession
) -> None:
    v2_app.dependency_overrides[get_settings] = lambda: v2_settings()
    staff = make_person(v2_app, "staff", staff=True, db=db)
    client = login(v2_app, staff)
    age(db, staff.user_id, seen=timedelta(minutes=20))
    assert client.get("/api/v1/auth/me").status_code == 200
    age(db, staff.user_id, seen=timedelta(minutes=31))
    assert client.get("/api/v1/auth/me").status_code == 401
    again = login(v2_app, staff)
    age(db, staff.user_id, seen=timedelta(minutes=1), created=timedelta(hours=13))
    assert again.get("/api/v1/auth/me").status_code == 401  # active but past the absolute limit


def test_flag_off_the_idle_policy_is_not_applied(app: FastAPI, db: OrmSession) -> None:
    app.dependency_overrides[get_settings] = lambda: build_test_settings()
    staff = make_person(app, "staff", staff=True, db=db)
    age(db, staff.user_id, seen=timedelta(days=3), created=timedelta(days=3))
    assert staff.client.get("/api/v1/auth/me").status_code == 200
    assert staff.client.get("/api/v1/auth/sessions").json() == {"detail": "Not Found"}


def test_the_device_list_marks_the_current_session(v2_app: FastAPI, db: OrmSession) -> None:
    v2_app.dependency_overrides[get_settings] = lambda: v2_settings()
    person = make_person(v2_app, "devices", db=db)
    other = login(v2_app, person, **{"User-Agent": "Phone/2"})
    rows = other.get("/api/v1/auth/sessions").json()
    assert len(rows) == 2
    assert [r["current"] for r in rows].count(True) == 1
    assert next(r for r in rows if r["current"])["user_agent"] == "Phone/2"
    assert set(rows[0]) == {
        "id",
        "created_at",
        "last_seen_at",
        "user_agent",
        "current",
    }  # no hashes


def test_revoke_all_keeps_or_drops_the_current_session(v2_app: FastAPI, db: OrmSession) -> None:
    v2_app.dependency_overrides[get_settings] = lambda: v2_settings()
    person = make_person(v2_app, "everywhere", db=db)
    laptop = login(v2_app, person)
    phone = login(v2_app, person)
    done = laptop.post("/api/v1/auth/sessions/revoke-all", json={}, headers=csrf_headers(laptop))
    assert done.status_code == 200 and done.json() == {"revoked": 2}  # the registration + the phone
    assert laptop.get("/api/v1/auth/me").status_code == 200
    assert phone.get("/api/v1/auth/me").status_code == 401
    assert person.client.get("/api/v1/auth/me").status_code == 401
    final = laptop.post(
        "/api/v1/auth/sessions/revoke-all",
        json={"keep_current": False},
        headers=csrf_headers(laptop),
    )
    assert final.status_code == 200 and final.json() == {"revoked": 1}
    assert laptop.get("/api/v1/auth/me").status_code == 401
    events = list(
        db.scalars(select(AuditEvent).where(AuditEvent.action == "auth.sessions_revoked"))
    )
    assert [e.metadata_json["kept_current"] for e in events] == [True, False]


def test_revoke_all_needs_csrf_and_a_session(v2_app: FastAPI, db: OrmSession) -> None:
    v2_app.dependency_overrides[get_settings] = lambda: v2_settings()
    person = make_person(v2_app, "csrf", db=db)
    assert person.client.post("/api/v1/auth/sessions/revoke-all", json={}).status_code == 403
    anonymous = TestClient(v2_app, raise_server_exceptions=False)
    assert anonymous.post("/api/v1/auth/sessions/revoke-all", json={}).status_code in (401, 403)


def test_logout_is_audited_when_the_flag_is_on_only(v2_app: FastAPI, db: OrmSession) -> None:
    v2_app.dependency_overrides[get_settings] = lambda: v2_settings()
    person = make_person(v2_app, "bye", db=db)
    assert (
        person.client.post("/api/v1/auth/logout", headers=csrf_headers(person.client)).status_code
        == 200
    )
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "auth.logout"))
    assert event is not None and event.actor_user_id == person.user_id
    v2_app.dependency_overrides[get_settings] = lambda: build_test_settings()
    other = make_person(v2_app, "bye2", db=db)
    other.client.post("/api/v1/auth/logout", headers=csrf_headers(other.client))
    assert len(list(db.scalars(select(AuditEvent).where(AuditEvent.action == "auth.logout")))) == 1
