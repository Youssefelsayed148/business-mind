# ruff: noqa: F811
"""Phase 5D: the combined overview. A fixed dataset; every number must equal what the source tables
hold, other organizations and playground threads never count, and Many's gaps are stated.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from sqlalchemy import text, update
from sqlalchemy.orm import Session

from app.chat.conversations import append_message
from app.core.config import get_settings
from app.db.models import Contact, Conversation, CustomerLink, Message, UsageEvent
from tests.helpers import make_bot, seeded_tenant
from tests.test_customer_links import (  # type: ignore[attr-defined]  # noqa: F401
    _connection,
    _map,
    many,
    proxy_settings,
    uni_app,
)

OLD = datetime.now(UTC) - timedelta(days=100)


def _conversation(
    db: Session, users: Any, connection: Any, source: str, **extra: Any
) -> Conversation:
    conversation = Conversation(
        tenant_id=users.tenant_id,
        bot_id=connection.bot_id,
        source=source,
        channel="whatsapp" if source == "channel" else "website",
        connection_id=connection.id if source == "channel" else None,
        external_conversation_id=f"c-{uuid4().hex[:8]}" if source == "channel" else None,
        mode=extra.get("mode", "ai"),
        status=extra.get("status", "open"),
    )
    db.add(conversation)
    db.commit()
    return conversation


def _say(db: Session, conversation: Conversation, sender: str, *, old: bool = False) -> None:
    message = append_message(db, conversation, sender_type=sender, text="x", can_answer=True)
    if old:
        db.execute(update(Message).where(Message.id == message.id).values(created_at=OLD))
    db.commit()


def _usage(
    db: Session, users: Any, bot_id: Any, tokens: int, cost: float | None, **extra: Any
) -> None:
    payload: dict[str, Any] = {
        "accounted_tokens": tokens,
        "cost_usd": cost,
        **extra.get("payload", {}),
    }
    event = UsageEvent(
        tenant_id=users.tenant_id,
        bot_id=bot_id,
        kind="ai_usage",
        external_key=f"ai:{uuid4()}",
        payload=payload,
    )
    db.add(event)
    db.flush()
    if extra.get("old"):
        db.execute(update(UsageEvent).where(UsageEvent.id == event.id).values(created_at=OLD))
    db.commit()


def _link(
    db: Session, users: Any, platform: str, state: str, *, contact: bool = False, lead: bool = False
) -> None:
    contact_id = None
    if contact:
        row = Contact(tenant_id=users.tenant_id, display_name="C", source_channel=platform)
        db.add(row)
        db.flush()
        contact_id = row.id
    db.add(
        CustomerLink(
            tenant_id=users.tenant_id,
            contact_id=contact_id,
            platform=platform,
            many_channel_id=str(uuid4()),
            external_id_digest=uuid4().hex + uuid4().hex,
            many_lead_id=str(uuid4()) if lead else None,
            source="many_lead" if lead else "delegated_event",
            state=state,
        )
    )
    db.commit()


def _dataset(uni_app: FastAPI, db: Session, label: str) -> Any:
    users = seeded_tenant(uni_app, db, prefix=label)
    _map(db, users.tenant_id)
    bot_id = make_bot(users)["id"]
    connection = _connection(db, users, "whatsapp", str(uuid4()), bot_id=bot_id)
    # Links: whatsapp linked 1 + many_only 2; instagram many_only 1; facebook saas_only 1; 1 erased.
    _link(db, users, "whatsapp", "linked", contact=True, lead=True)
    _link(db, users, "whatsapp", "many_only", lead=True)
    _link(db, users, "whatsapp", "many_only", lead=True)
    _link(db, users, "instagram", "many_only", lead=True)
    _link(db, users, "facebook", "saas_only", contact=True)
    _link(db, users, "whatsapp", "erased")
    # Chat: two channel conversations (one handed to a human), one playground thread.
    ai_thread = _conversation(db, users, connection, "channel")
    human_thread = _conversation(db, users, connection, "channel", mode="human")
    playground = _conversation(db, users, connection, "playground")
    for sender in ("visitor", "visitor", "ai"):
        _say(db, ai_thread, sender)
    for sender in ("visitor", "agent"):
        _say(db, human_thread, sender)
    _say(db, ai_thread, "ai", old=True)  # outside the range
    for sender in ("visitor", "ai", "ai"):
        _say(db, playground, sender)  # playground never counts
    # AI usage: two real calls (one with a measured cost), one playground, one too old.
    _usage(db, users, bot_id, 100, 0.01)
    _usage(db, users, bot_id, 50, None)
    _usage(db, users, bot_id, 999, 9.0, payload={"source": "playground"})
    _usage(db, users, bot_id, 777, 7.0, old=True)
    return users


def _get(users: Any, role: str = "admin", query: str = "") -> Any:
    return users.call(role, "GET", f"/api/v1/tenants/{users.tenant_id}/customer-overview{query}")


def test_every_number_equals_the_sources(uni_app: FastAPI, db: Session, many: Any) -> None:
    users = _dataset(uni_app, db, "co-fixed")
    body = _get(users).json()
    wa = body["people"]["by_platform"]["whatsapp"]
    assert wa == {"linked": 1, "many_only": 2, "saas_only": 0, "conflict": 0, "total": 3}
    assert body["people"]["by_platform"]["instagram"]["many_only"] == 1
    assert body["people"]["by_platform"]["facebook"]["saas_only"] == 1
    assert body["people"]["known_to_outreach"] == 4  # leads: 1 linked + 2 + 1 instagram
    assert body["people"]["known_to_chat"] == 2  # two links have a chat contact
    chat = body["chat"]
    assert (chat["conversations"], chat["handoffs"]) == (2, 1)  # playground excluded
    assert chat["messages"] == {"visitor": 3, "ai": 1, "agent": 1}  # old and playground excluded
    assert chat["contacts"] == 2 and chat["new_contacts"] == 2
    ai = body["ai"]
    assert (ai["calls"], ai["tokens"], ai["calls_with_cost"], ai["cost_usd"]) == (2, 150, 1, 0.01)
    assert body["not_available"]  # Many's gaps are stated, not guessed
    # The same numbers straight from the tables.
    direct = db.execute(
        text(
            "SELECT count(*) FROM messages m JOIN conversations c ON c.id = m.conversation_id "
            "WHERE m.tenant_id = :t AND c.source <> 'playground' AND m.created_at > :since"
        ),
        {"t": users.tenant_id, "since": datetime.now(UTC) - timedelta(days=30)},
    ).scalar()
    assert direct == sum(chat["messages"].values())


def test_a_longer_range_includes_older_rows(uni_app: FastAPI, db: Session, many: Any) -> None:
    users = _dataset(uni_app, db, "co-range")
    body = _get(users, query="?days=365").json()
    assert body["chat"]["messages"]["ai"] == 2  # the old message now counts
    assert body["ai"]["calls"] == 3 and body["ai"]["tokens"] == 927  # 100 + 50 + 777


def test_another_organization_never_counts(uni_app: FastAPI, db: Session, many: Any) -> None:
    mine = _dataset(uni_app, db, "co-iso-a")
    other = _dataset(uni_app, db, "co-iso-b")
    a, b = _get(mine).json(), _get(other).json()
    assert a["people"] == b["people"] and a["chat"] == b["chat"]  # identical datasets, not summed
    assert a["chat"]["conversations"] == 2


def test_an_empty_organization_reports_zeros(uni_app: FastAPI, db: Session, many: Any) -> None:
    users = seeded_tenant(uni_app, db, prefix="co-empty")
    body = _get(users).json()
    assert body["people"]["by_platform"]["whatsapp"]["total"] == 0
    assert body["chat"]["messages"] == {"visitor": 0, "ai": 0, "agent": 0}
    assert body["ai"] == {**body["ai"], "calls": 0, "tokens": 0, "cost_usd": 0.0}


def test_roles_flag_and_range_bounds(uni_app: FastAPI, db: Session, many: Any) -> None:
    users = seeded_tenant(uni_app, db, prefix="co-roles")
    for role in ("editor", "viewer"):
        assert _get(users, role).status_code == 403
    assert _get(users, query="?days=0").status_code == 422
    assert _get(users, query="?days=366").status_code == 422
    uni_app.dependency_overrides[get_settings] = lambda: proxy_settings()
    assert _get(users).status_code == 404
