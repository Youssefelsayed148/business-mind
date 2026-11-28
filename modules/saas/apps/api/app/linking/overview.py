"""Combined overview for one organization (Phase 5D). Measured data only, every number labelled.

People come from the customer link (Many leads and SaaS contacts, by channel and state). Chat and
AI figures come from the SaaS tables (playground threads never count, as in the existing
analytics). Many holds no per-organization message counts or costs, so those are listed as not
available instead of being guessed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

PLATFORMS = ("whatsapp", "instagram", "facebook")
STATES = ("linked", "many_only", "saas_only", "conflict")

NOT_AVAILABLE = [
    "Messages handled by the outreach service, per organization",
    "Costs in the outreach service (it records none)",
]


def overview(db: Session, tenant_id: UUID, days: int) -> dict[str, Any]:
    end = datetime.now(UTC)
    start = (end - timedelta(days=days)).replace(microsecond=0)
    params = {"t": str(tenant_id), "start": start, "end": end}

    by_platform: dict[str, dict[str, int]] = {
        p: {**{s: 0 for s in STATES}, "total": 0} for p in PLATFORMS
    }
    for platform, state, n in db.execute(
        text(
            "SELECT platform, state, count(*) FROM customer_links "
            "WHERE tenant_id = CAST(:t AS uuid) AND state <> 'erased' GROUP BY platform, state"
        ),
        params,
    ):
        by_platform[platform][state] = n
        by_platform[platform]["total"] += n
    known = db.execute(
        text(
            "SELECT count(*) FILTER (WHERE many_lead_id IS NOT NULL), "
            "count(*) FILTER (WHERE contact_id IS NOT NULL) FROM customer_links "
            "WHERE tenant_id = CAST(:t AS uuid) AND state <> 'erased'"
        ),
        params,
    ).one()

    contacts = db.execute(
        text(
            "SELECT count(*), count(*) FILTER (WHERE created_at >= :start AND created_at <= :end) "
            "FROM contacts WHERE tenant_id = CAST(:t AS uuid)"
        ),
        params,
    ).one()
    conversations = db.execute(
        text(
            "SELECT count(*), "
            "count(*) FILTER (WHERE mode = 'human' OR status = 'waiting_human') "
            "FROM conversations WHERE tenant_id = CAST(:t AS uuid) AND source <> 'playground' "
            "AND created_at >= :start AND created_at <= :end"
        ),
        params,
    ).one()
    messages = {"visitor": 0, "ai": 0, "agent": 0}
    for sender, n in db.execute(
        text(
            "SELECT m.sender_type, count(*) FROM messages m "
            "JOIN conversations c ON c.id = m.conversation_id AND c.tenant_id = m.tenant_id "
            "WHERE m.tenant_id = CAST(:t AS uuid) AND c.source <> 'playground' "
            "AND m.created_at >= :start AND m.created_at <= :end "
            "AND m.sender_type IN ('visitor', 'ai', 'agent') GROUP BY m.sender_type"
        ),
        params,
    ):
        messages[sender] = n
    usage = db.execute(
        text(
            "SELECT count(*), "
            "COALESCE(sum((payload->>'accounted_tokens')::bigint), 0), "
            "count(*) FILTER (WHERE payload->>'cost_usd' IS NOT NULL), "
            "COALESCE(sum((payload->>'cost_usd')::numeric), 0) "
            "FROM usage_events WHERE tenant_id = CAST(:t AS uuid) AND kind = 'ai_usage' "
            "AND COALESCE(payload->>'source', '') <> 'playground' "
            "AND created_at >= :start AND created_at <= :end"
        ),
        params,
    ).one()

    return {
        "range": {"from": start.isoformat(), "to": end.isoformat(), "days": days},
        "people": {
            "source": "Customer link: Many leads and chat contacts",
            "by_platform": by_platform,
            "known_to_outreach": known[0],
            "known_to_chat": known[1],
        },
        "chat": {
            "source": "Chat inbox (SaaS)",
            "contacts": contacts[0],
            "new_contacts": contacts[1],
            "conversations": conversations[0],
            "handoffs": conversations[1],
            "messages": messages,
        },
        "ai": {
            "source": "Chat inbox (SaaS)",
            "calls": usage[0],
            "tokens": int(usage[1]),
            "calls_with_cost": usage[2],
            "cost_usd": float(usage[3]),
        },
        "not_available": NOT_AVAILABLE,
    }
