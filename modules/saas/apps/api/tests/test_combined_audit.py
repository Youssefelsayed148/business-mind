# ruff: noqa: F811
"""Phase 5E: the combined audit view for platform staff. A fake Many answers its log."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.config import get_settings
from app.db.models import AuditEvent
from app.identity import many_proxy
from tests.helpers import seeded_tenant
from tests.test_customer_links import (  # noqa: F401  (fixtures and helpers)
    FakeMany,
    _ok,
    many,
    proxy_settings,
    uni_app,
)

NOW = datetime.now(UTC)


def _event(db: Session, tenant_id: Any, action: str, minutes_ago: int) -> None:
    record_audit(
        db,
        action=action,
        tenant_id=tenant_id,
        actor_user_id=None,
        target_type="x",
        target_id="SECRET-TARGET",
        metadata={"email": "secret@example.com"},
    )
    db.commit()
    row = (
        db.query(AuditEvent)
        .filter(AuditEvent.action == action)
        .order_by(AuditEvent.created_at.desc())
        .first()
    )
    db.execute(
        update(AuditEvent)
        .where(AuditEvent.id == row.id)
        .values(created_at=NOW - timedelta(minutes=minutes_ago))
    )
    db.commit()


def _many_log(event_type: str, minutes_ago: int, level: str = "info") -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "level": level,
        "event_type": event_type,
        "message": f"Message for {event_type}",
        "metadata": {"actor_email": "secret@example.com"},
        "created_at": (NOW - timedelta(minutes=minutes_ago)).isoformat(),
    }


def _get(users: Any, query: str = "", role: str = "staff") -> Any:
    return users.call(role, "GET", f"/api/v1/platform/audit{query}")


def test_both_systems_are_merged_newest_first_and_tagged(
    uni_app: FastAPI, db: Session, many: FakeMany
) -> None:
    users = seeded_tenant(uni_app, db, prefix="au-merge")
    _event(db, users.tenant_id, "customer_links.sync", 10)
    _event(db, users.tenant_id, "customer_erasure.complete", 30)
    many.plan.append(
        _ok([_many_log("campaign_activated", 20), _many_log("send_failed", 5, "error")])
    )
    body = _get(users).json()
    rows = [(r["source"], r["action"]) for r in body["items"]]
    saas = [r for r in rows if r[0] == "saas" and r[1].startswith("customer_")]
    assert saas == [("saas", "customer_links.sync"), ("saas", "customer_erasure.complete")]
    # Strictly newest first across the two sources.
    ours = [
        (r["source"], r["action"])
        for r in body["items"]
        if r["action"]
        in {"send_failed", "customer_links.sync", "campaign_activated", "customer_erasure.complete"}
    ]
    assert ours == [
        ("many", "send_failed"),
        ("saas", "customer_links.sync"),
        ("many", "campaign_activated"),
        ("saas", "customer_erasure.complete"),
    ]
    assert body["many_unavailable"] is False
    levels = {r["action"]: r["level"] for r in body["items"] if r["source"] == "many"}
    assert levels["send_failed"] == "error"


def test_no_metadata_or_target_leaves_either_system(
    uni_app: FastAPI, db: Session, many: FakeMany
) -> None:
    users = seeded_tenant(uni_app, db, prefix="au-leak")
    _event(db, users.tenant_id, "customer_links.sync", 1)
    many.plan.append(_ok([_many_log("campaign_activated", 2)]))
    text = _get(users).text
    assert "secret@example.com" not in text and "SECRET-TARGET" not in text
    assert "metadata" not in text and "actor_email" not in text


def test_a_tenant_filter_shows_only_that_organization_and_says_why(
    uni_app: FastAPI, db: Session, many: FakeMany
) -> None:
    a = seeded_tenant(uni_app, db, prefix="au-a")
    b = seeded_tenant(uni_app, db, prefix="au-b")
    _event(db, a.tenant_id, "only.in.a", 5)
    _event(db, b.tenant_id, "only.in.b", 5)
    body = _get(a, f"?tenant_id={a.tenant_id}").json()
    actions = {r["action"] for r in body["items"]}
    assert "only.in.a" in actions and "only.in.b" not in actions
    assert all(r["source"] == "saas" for r in body["items"])
    assert body["notes"] and many.forwarded == []  # Many was not even asked


def test_many_down_still_shows_the_chat_side_and_says_so(
    uni_app: FastAPI, db: Session, many: FakeMany
) -> None:
    users = seeded_tenant(uni_app, db, prefix="au-down")
    _event(db, users.tenant_id, "customer_links.sync", 1)
    many.plan.append(many_proxy.ManyUnavailable("down"))
    body = _get(users).json()
    assert body["many_unavailable"] is True and body["notes"]
    assert any(r["action"] == "customer_links.sync" for r in body["items"])


def test_source_choice_limit_staff_only_and_flag(
    uni_app: FastAPI, db: Session, many: FakeMany
) -> None:
    users = seeded_tenant(uni_app, db, prefix="au-opts")
    for n in range(5):
        _event(db, users.tenant_id, f"a.{n}", n + 1)
    only_saas = _get(users, "?source=saas&limit=3").json()
    assert len(only_saas["items"]) == 3 and many.forwarded == []
    assert _get(users, "?source=bogus").status_code == 422
    assert _get(users, "?limit=201").status_code == 422
    for role in ("admin", "editor", "viewer"):
        assert _get(users, "", role).status_code == 403
    uni_app.dependency_overrides[get_settings] = lambda: proxy_settings()
    assert _get(users).status_code == 404
