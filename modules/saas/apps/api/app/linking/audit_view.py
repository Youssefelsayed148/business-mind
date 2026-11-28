"""One audit view for platform staff (Phase 5E): SaaS audit events and Many logs, newest first.

Each row carries its source and holds only the action, a short sentence and a level: no metadata
(either system's metadata can hold personal data). Many's log is global and names no organization,
so a tenant filter shows SaaS events only and says so. Both systems keep writing their own store;
nothing is copied.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import AuditEvent, User
from app.identity import many_proxy


def _saas_rows(db: Session, tenant_id: UUID | None, limit: int) -> list[dict[str, Any]]:
    query = select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)
    if tenant_id is not None:
        query = query.where(AuditEvent.tenant_id == tenant_id)
    return [
        {
            "source": "saas",
            "at": row.created_at,
            "action": row.action,
            "summary": row.action.replace(".", " ").replace("_", " "),
            "level": "info",
            "tenant_id": str(row.tenant_id) if row.tenant_id else None,
        }
        for row in db.scalars(query)
    ]


def _parse(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None
    if parsed is not None and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _many_rows(db: Session, settings: Settings, staff: User, limit: int) -> list[dict[str, Any]]:
    token = many_proxy.many_token(
        db,
        settings,
        staff,
        org_id=None,
        staff=True,
        fingerprint="staff",
        session_token_hash=None,
    )
    response = many_proxy.forward(
        settings,
        token=token,
        workspace_id=None,
        method="GET",
        path="logs",
        query=f"limit={limit}",
        request_headers={"accept": "application/json"},
        body=None,
    )
    if response.status != 200:
        raise many_proxy.ManyUnavailable(f"logs answered {response.status}")
    try:
        rows = json.loads(response.body)
    except ValueError as exc:
        raise many_proxy.ManyUnavailable("logs answer unusable") from exc
    if not isinstance(rows, list):
        raise many_proxy.ManyUnavailable("logs answer unusable")
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        at = _parse(row.get("created_at"))
        if at is None:
            continue
        level = str(row.get("level") or "info")
        out.append(
            {
                "source": "many",
                "at": at,
                "action": str(row.get("event_type") or "")[:100],
                "summary": str(row.get("message") or "")[:300],
                "level": level if level in {"info", "warning", "error", "danger"} else "info",
                "tenant_id": None,
            }
        )
    return out


def combined(
    db: Session,
    settings: Settings,
    staff: User,
    *,
    tenant_id: UUID | None,
    source: str,
    limit: int,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    notes: list[str] = []
    many_failed = False
    if source in ("all", "saas"):
        rows += _saas_rows(db, tenant_id, limit)
    if source in ("all", "many"):
        if tenant_id is not None:
            notes.append(
                "Outreach-service entries are not tied to one organization, so they are left out."
            )
        else:
            try:
                rows += _many_rows(db, settings, staff, limit)
            except many_proxy.ManyUnavailable:
                many_failed = True
                notes.append(
                    "The outreach service did not answer; only chat-inbox entries are shown."
                )
    rows.sort(key=lambda r: r["at"], reverse=True)
    items = [{**r, "at": r["at"].isoformat()} for r in rows[:limit]]
    return {"items": items, "many_unavailable": many_failed, "notes": notes}
