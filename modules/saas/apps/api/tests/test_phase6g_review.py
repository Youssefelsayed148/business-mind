# ruff: noqa: F811
"""Phase 6G: regression tests for the security-review findings fixed in the data-unification code.

G-01 retry after a crash between the erase commit and the case update (no duplicate event, no 500);
G-02 a missing channel connection must not mark the person erased; G-03 Many's free text never
reaches the combined audit; G-04 a staff-set channel reference cannot change the Many path.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import ChannelConnection, ChannelEvent, Contact, ErasureCase
from app.identity import many_proxy
from tests.helpers import seeded_tenant
from tests.test_combined_audit import _get, _many_log
from tests.test_customer_erasure import (
    ERASED,
    _erase,
    _filled,
    _link,
    _privacy_calls,
)
from tests.test_customer_links import (  # type: ignore[attr-defined]  # noqa: F401
    FakeMany,
    _ok,
    many,
    proxy_settings,
    uni_app,
)


def _retry(users: Any, case_id: str) -> Any:
    return users.call(
        "admin", "POST", f"/api/v1/tenants/{users.tenant_id}/erasure-cases/{case_id}/retry"
    )


def test_a_missing_connection_does_not_mark_the_person_erased(
    uni_app: FastAPI, db: Session, many: FakeMany
) -> None:  # G-02
    users, w1, _w2, contact = _filled(uni_app, db, many, "g02")
    contact_id = contact.id
    link = _link(db, users, "linked", w1)
    for connection in db.scalars(
        select(ChannelConnection).where(ChannelConnection.tenant_id == users.tenant_id)
    ):
        connection.many_channel_ref = "somewhere-else"
    db.commit()
    response = _erase(users, link.id)
    assert response.status_code == 202, response.text
    assert response.json()["state"] == "needs_action"
    assert response.json()["reason"] == "connection_missing"
    db.expire_all()
    kept = db.get(type(link), link.id)
    assert kept is not None and kept.state == "linked"  # still visible, not hidden as erased
    assert db.scalar(select(func.count(Contact.id)).where(Contact.id == contact_id)) == 1
    assert _privacy_calls(many) == []  # Many was not asked


def test_a_retry_after_a_crash_between_commit_and_update_finishes_without_a_500(
    uni_app: FastAPI, db: Session, many: FakeMany
) -> None:  # G-01
    users, w1, _w2, _contact = _filled(uni_app, db, many, "g01")
    link = _link(db, users, "linked", w1)
    many.plan.append(many_proxy.ManyUnavailable("down"))
    first = _erase(users, link.id)
    case_id = first.json()["id"]
    # Put the rows back as they were when the process died after the SaaS erase committed but
    # before the case and link were updated: the erase event exists, the case is still open.
    db.expire_all()
    case = db.get(ErasureCase, case_id)
    assert case is not None
    case.state = "requested"
    held = db.get(type(link), link.id)
    assert held is not None
    held.state = "linked"
    db.commit()
    events_before = db.scalar(select(func.count(ChannelEvent.id)))
    many.plan.append(ERASED)
    retried = _retry(users, case_id)
    assert retried.status_code == 202, retried.text
    assert retried.json()["state"] == "complete"
    db.expire_all()
    assert db.scalar(select(func.count(ChannelEvent.id))) == events_before  # no second event


def test_a_staff_set_channel_reference_cannot_change_the_many_path(
    uni_app: FastAPI, db: Session, many: FakeMany
) -> None:  # G-04
    users, w1, _w2, _contact = _filled(uni_app, db, many, "g04")
    link = _link(db, users, "linked", w1)
    many.plan.append(many_proxy.ManyUnavailable("down"))
    case_id = _erase(users, link.id).json()["id"]
    db.expire_all()
    case = db.get(ErasureCase, case_id)
    assert case is not None
    case.many_channel_id = "../../auth/login?x=1"
    db.commit()
    before = len(many.forwarded)
    retried = _retry(users, case_id)
    assert retried.json()["state"] == "needs_action"
    assert retried.json()["reason"] == "channel_ref_invalid"
    assert len(many.forwarded) == before  # nothing was sent to Many


def test_many_free_text_never_reaches_the_combined_audit(
    uni_app: FastAPI, db: Session, many: FakeMany
) -> None:  # G-03
    users = seeded_tenant(uni_app, db, prefix="g03")
    row = _many_log("sso_login", 5)
    row["message"] = f"{uuid4().hex[:6]}@example.com signed in through SSO"
    many.plan.append(_ok([row]))
    body = _get(users).json()
    many_rows = [r for r in body["items"] if r["source"] == "many"]
    assert [r["summary"] for r in many_rows] == ["sso_login"]
    assert "@example.com" not in str(body)
