"""Location filters wired into the query sites (design 4.2, Phase 3 PR D).

A location-limited caller sees only rows whose location is in their list. Organization-wide
rows (NULL location, and every website conversation, which has no channel connection) are
visible to unrestricted callers only. Synthetic data only.
"""

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from cryptography.fernet import Fernet
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.channels.secrets import encrypt_secret
from app.db.models import (
    Bot,
    ChannelConnection,
    Contact,
    Conversation,
    FollowUp,
    Location,
    MembershipLocation,
    Message,
    Source,
    Tenant,
    UsageEvent,
)
from app.inbox.listing import _notification_counts_for
from tests.helpers import csrf_headers
from tests.identity_helpers import Person, join, make_person, make_tenant

KEY = Fernet.generate_key().decode("ascii")


@dataclass
class World:
    tenant_id: UUID
    bot_id: UUID
    north: UUID
    south: UUID
    conn_north: UUID
    conn_south: UUID
    conn_org: UUID
    conv_north: UUID
    conv_south: UUID
    conv_org: UUID  # a channel conversation on a connection without a location
    conv_web: UUID  # website conversation: no connection, so organization-wide
    contact_north: UUID
    contact_south: UUID
    contact_org: UUID
    contact_mixed: UUID  # located north, but one of its conversations is in the south
    source_north: UUID
    source_south: UUID
    source_org: UUID
    full_admin: Person
    full_agent: Person
    lim_admin: Person  # north only
    lim_agent: Person  # north only
    lim_both: Person  # north and south

    def url(self, path: str) -> str:
        return f"/api/v1/tenants/{self.tenant_id}{path}"

    def bot(self, path: str) -> str:
        return self.url(f"/bots/{self.bot_id}{path}")


def _connection(
    db: Session, tenant_id: UUID, bot_id: UUID, name: str, location_id: UUID | None, ref: str
) -> UUID:
    row = ChannelConnection(
        tenant_id=tenant_id,
        bot_id=bot_id,
        channel="whatsapp",
        display_name=name,
        many_base_url="https://many.example.test",
        many_channel_ref=f"{ref}-{uuid4().hex[:8]}",
        status="active",
        ai_enabled=True,
        secret_ciphertext=encrypt_secret("fixture-secret", KEY),
        secret_key_version=1,
        health_status="unknown",
        location_id=location_id,
    )
    db.add(row)
    db.flush()
    return row.id


def _conversation(
    db: Session,
    tenant_id: UUID,
    bot_id: UUID,
    connection_id: UUID | None,
    contact_id: UUID | None = None,
    *,
    status: str = "open",
    text: str = "hello",
) -> UUID:
    row = Conversation(
        tenant_id=tenant_id,
        bot_id=bot_id,
        contact_id=contact_id,
        source="channel" if connection_id else "website",
        channel="whatsapp" if connection_id else "website",
        connection_id=connection_id,
        session_id=None,
        mode="ai",
        status=status,
        last_message_at=datetime.now(UTC),
    )
    db.add(row)
    db.flush()
    db.add(
        Message(
            tenant_id=tenant_id,
            bot_id=bot_id,
            conversation_id=row.id,
            sender_type="visitor",
            text=text,
        )
    )
    db.add(
        UsageEvent(
            tenant_id=tenant_id,
            bot_id=bot_id,
            kind="lead",
            conversation_id=row.id,
            external_key=f"lead:{row.id}",
        )
    )
    db.flush()
    return row.id


def _contact(db: Session, tenant_id: UUID, name: str, location_id: UUID | None) -> UUID:
    row = Contact(
        id=uuid4(),
        tenant_id=tenant_id,
        display_name=name,
        email=f"{name}-{uuid4().hex[:6]}@example.com",
        source_channel="whatsapp",
        location_id=location_id,
    )
    db.add(row)
    db.flush()
    return row.id


def _source(
    db: Session, tenant_id: UUID, bot_id: UUID, user_id: UUID, name: str, loc: UUID | None
) -> UUID:
    row = Source(
        id=uuid4(),
        tenant_id=tenant_id,
        bot_id=bot_id,
        kind="txt",
        original_name=name,
        storage_key=f"test/{uuid4().hex}",
        size_bytes=10,
        sha256=secrets.token_hex(32),
        status="ingested",
        created_by=user_id,
        location_id=loc,
    )
    db.add(row)
    db.flush()
    return row.id


def build_world(app: FastAPI, db: Session, name: str = "World") -> World:
    tenant_id = make_tenant(db, name)
    db.execute(update(Tenant).where(Tenant.id == tenant_id).values(plan_label="business"))
    bot = Bot(
        id=uuid4(),
        tenant_id=tenant_id,
        name="Bot",
        status="draft",
        config={},
        widget_locator="w" + secrets.token_hex(16),
    )
    db.add(bot)
    north = Location(id=uuid4(), tenant_id=tenant_id, name="North")
    south = Location(id=uuid4(), tenant_id=tenant_id, name="South")
    db.add_all([north, south])
    db.flush()
    full_admin = make_person(app, "full-admin", db=db)
    full_agent = make_person(app, "full-agent", db=db)
    lim_admin = make_person(app, "lim-admin", db=db)
    lim_agent = make_person(app, "lim-agent", db=db)
    lim_both = make_person(app, "lim-both", db=db)
    join(db, tenant_id, full_admin.user_id, "admin")
    join(db, tenant_id, full_agent.user_id, "agent")
    for person, role, places in (
        (lim_admin, "admin", (north.id,)),
        (lim_agent, "agent", (north.id,)),
        (lim_both, "admin", (north.id, south.id)),
    ):
        join(db, tenant_id, person.user_id, role, location_scope="limited")
        for place in places:
            db.add(
                MembershipLocation(tenant_id=tenant_id, user_id=person.user_id, location_id=place)
            )
    db.flush()
    conn_n = _connection(db, tenant_id, bot.id, "North line", north.id, "n")
    conn_s = _connection(db, tenant_id, bot.id, "South line", south.id, "s")
    conn_o = _connection(db, tenant_id, bot.id, "Org line", None, "o")
    c_north = _contact(db, tenant_id, "north", north.id)
    c_south = _contact(db, tenant_id, "south", south.id)
    c_org = _contact(db, tenant_id, "org", None)
    c_mixed = _contact(db, tenant_id, "mixed", north.id)
    world = World(
        tenant_id=tenant_id,
        bot_id=bot.id,
        north=north.id,
        south=south.id,
        conn_north=conn_n,
        conn_south=conn_s,
        conn_org=conn_o,
        conv_north=_conversation(db, tenant_id, bot.id, conn_n, c_north, text="north question"),
        conv_south=_conversation(db, tenant_id, bot.id, conn_s, c_south, text="south question"),
        conv_org=_conversation(db, tenant_id, bot.id, conn_o, c_org, status="waiting_human"),
        conv_web=_conversation(db, tenant_id, bot.id, None, None, text="web question"),
        contact_north=c_north,
        contact_south=c_south,
        contact_org=c_org,
        contact_mixed=c_mixed,
        source_north=_source(db, tenant_id, bot.id, full_admin.user_id, "north.txt", north.id),
        source_south=_source(db, tenant_id, bot.id, full_admin.user_id, "south.txt", south.id),
        source_org=_source(db, tenant_id, bot.id, full_admin.user_id, "org.txt", None),
        full_admin=full_admin,
        full_agent=full_agent,
        lim_admin=lim_admin,
        lim_agent=lim_agent,
        lim_both=lim_both,
    )
    # The mixed contact also talks on the south line.
    _conversation(db, tenant_id, bot.id, conn_s, c_mixed, text="mixed south")
    db.commit()
    return world


def ids_in(response: Any, *wanted: UUID) -> set[UUID]:
    """Which of the given ids appear anywhere in a JSON response."""
    assert response.status_code == 200, response.text
    text = response.text
    return {item for item in wanted if str(item) in text}


def test_inbox_list_counts_and_detail_follow_the_callers_locations(
    v2_app: FastAPI, db: Session
) -> None:
    w = build_world(v2_app, db)
    every = (w.conv_north, w.conv_south, w.conv_org, w.conv_web)
    full = w.full_agent.client.get(w.url("/inbox"))
    assert ids_in(full, *every) == set(every)
    limited = w.lim_agent.client.get(w.url("/inbox"))
    assert ids_in(limited, *every) == {w.conv_north}  # org-wide and website rows are hidden
    assert limited.json()["total"] == 1
    both = w.lim_both.client.get(w.url("/inbox"))
    assert ids_in(both, *every) == {w.conv_north, w.conv_south}
    # Counts: the org-line conversation is waiting for a human; a limited agent cannot see it.
    assert w.full_agent.client.get(w.url("/inbox/counts")).json()["waiting_human"] == 1
    assert w.lim_agent.client.get(w.url("/inbox/counts")).json()["waiting_human"] == 0
    assert w.lim_agent.client.get(w.url("/inbox/counts")).json()["unread_conversations"] == 1
    # Detail, bot-scoped list and detail.
    for hidden in (w.conv_south, w.conv_org, w.conv_web):
        assert w.lim_agent.client.get(w.url(f"/conversations/{hidden}")).status_code == 404
        assert w.lim_agent.client.get(w.bot(f"/conversations/{hidden}")).status_code == 404
        assert w.full_agent.client.get(w.url(f"/conversations/{hidden}")).status_code == 200
    assert w.lim_agent.client.get(w.url(f"/conversations/{w.conv_north}")).status_code == 200
    by_bot = w.lim_agent.client.get(w.bot("/conversations"))
    assert ids_in(by_bot, *every) == {w.conv_north} and by_bot.json()["total"] == 1
    assert ids_in(w.full_agent.client.get(w.bot("/conversations")), *every) == set(every)


def test_inbox_actions_on_out_of_scope_conversations_answer_404(
    v2_app: FastAPI, db: Session
) -> None:
    w = build_world(v2_app, db)
    client = w.lim_agent.client
    headers = csrf_headers(client)
    for hidden in (w.conv_south, w.conv_org, w.conv_web):
        for path, body in (
            (f"/conversations/{hidden}/takeover", None),
            (f"/conversations/{hidden}/return-to-ai", None),
            (f"/conversations/{hidden}/resolve", None),
            (f"/conversations/{hidden}/assign", {"assigned_user_id": None}),
            (f"/conversations/{hidden}/messages", {"text": "hi"}),
            (f"/conversations/{hidden}/notes", {"text": "n"}),
            (f"/inbox/{hidden}/read", None),
            (f"/inbox/{hidden}/tags", {"tag": "vip"}),
        ):
            response = client.post(w.url(path), json=body, headers=headers)
            assert response.status_code == 404, (path, response.status_code, response.text)
        assert client.delete(w.url(f"/inbox/{hidden}/tags/vip"), headers=headers).status_code == 404
    # The same actions are reachable for the in-scope conversation (not a 404).
    for path, body in (
        (f"/conversations/{w.conv_north}/notes", {"text": "n"}),
        (f"/inbox/{w.conv_north}/read", None),
        (f"/inbox/{w.conv_north}/tags", {"tag": "vip"}),
    ):
        assert client.post(w.url(path), json=body, headers=headers).status_code in (200, 201)
    # Admin-level delete of a hidden conversation is also a 404.
    admin = w.lim_admin.client
    assert (
        admin.delete(
            w.bot(f"/conversations/{w.conv_south}"), headers=csrf_headers(admin)
        ).status_code
        == 404
    )


def test_notification_counts_for_the_event_stream_use_the_same_scope(db: Session) -> None:
    # Built without HTTP: the SSE generator shares this helper with the counts route.
    tenant_id = make_tenant(db, "Counts")
    bot = Bot(id=uuid4(), tenant_id=tenant_id, name="B", status="draft", config={})
    place = Location(id=uuid4(), tenant_id=tenant_id, name="Here")
    other = Location(id=uuid4(), tenant_id=tenant_id, name="There")
    db.add_all([bot, place, other])
    db.flush()
    mine = _connection(db, tenant_id, bot.id, "Mine", place.id, "m")
    theirs = _connection(db, tenant_id, bot.id, "Theirs", other.id, "t")
    _conversation(db, tenant_id, bot.id, mine, status="waiting_human")
    _conversation(db, tenant_id, bot.id, theirs, status="waiting_human")
    _conversation(db, tenant_id, bot.id, None, status="waiting_human")
    db.commit()
    user_id = uuid4()
    assert _notification_counts_for(db, tenant_id, user_id)["waiting_human"] == 3
    assert (
        _notification_counts_for(db, tenant_id, user_id, frozenset({place.id}))["waiting_human"]
        == 1
    )
    assert _notification_counts_for(db, tenant_id, user_id, frozenset())["waiting_human"] == 0


def test_contacts_list_detail_update_export_and_stages(v2_app: FastAPI, db: Session) -> None:
    w = build_world(v2_app, db)
    every = (w.contact_north, w.contact_south, w.contact_org, w.contact_mixed)
    assert ids_in(w.full_agent.client.get(w.url("/contacts")), *every) == set(every)
    limited = w.lim_agent.client.get(w.url("/contacts"))
    assert ids_in(limited, *every) == {w.contact_north, w.contact_mixed}
    assert ids_in(w.lim_both.client.get(w.url("/contacts")), *every) == set(every) - {w.contact_org}
    for hidden in (w.contact_south, w.contact_org):
        assert w.lim_agent.client.get(w.url(f"/contacts/{hidden}")).status_code == 404
        assert (
            w.lim_agent.client.patch(
                w.url(f"/contacts/{hidden}"),
                json={"display_name": "x"},
                headers=csrf_headers(w.lim_agent.client),
            ).status_code
            == 404
        )
        assert w.full_agent.client.get(w.url(f"/contacts/{hidden}")).status_code == 200
    detail = w.lim_agent.client.get(w.url(f"/contacts/{w.contact_mixed}"))
    assert detail.status_code == 200
    # The mixed contact's southern conversation is not in its timeline for the northern member.
    timeline_ids = {
        item["id"] for item in detail.json()["timeline"] if item["type"] == "conversation"
    }
    assert len(timeline_ids) == 0  # its only northern link is the contact; no northern thread
    full_detail = w.full_agent.client.get(w.url(f"/contacts/{w.contact_mixed}"))
    assert len([i for i in full_detail.json()["timeline"] if i["type"] == "conversation"]) == 1
    # Export (admin): only the caller's rows.
    export = w.lim_admin.client.get(w.url("/contacts/export.csv"))
    assert export.status_code == 200
    assert str(w.contact_north) in export.text and str(w.contact_south) not in export.text
    assert str(w.contact_org) not in export.text
    assert str(w.contact_org) in w.full_admin.client.get(w.url("/contacts/export.csv")).text
    # Stage rename rewrites every contact of the organization: unrestricted callers only.
    headers = csrf_headers(w.lim_admin.client)
    w.lim_admin.client.get(w.url("/contacts/stages"))
    refused = w.lim_admin.client.patch(
        w.url("/contacts/stages"), json={"old_name": "new", "name": "fresh"}, headers=headers
    )
    assert refused.status_code == 403
    allowed = w.full_admin.client.patch(
        w.url("/contacts/stages"),
        json={"old_name": "new", "name": "fresh"},
        headers=csrf_headers(w.full_admin.client),
    )
    assert allowed.status_code == 200, allowed.text


def test_contact_creation_takes_a_location(v2_app: FastAPI, db: Session) -> None:
    w = build_world(v2_app, db)

    def create(person: Person, **extra: Any) -> Any:
        return person.client.post(
            w.url("/contacts"),
            json={"display_name": "New", "email": f"n-{uuid4().hex[:8]}@example.com", **extra},
            headers=csrf_headers(person.client),
        )

    def location_of(response: Any) -> UUID | None:
        assert response.status_code == 201, response.text
        return db.scalar(
            select(Contact.location_id).where(Contact.id == UUID(response.json()["id"]))
        )

    # A caller limited to one location creates into it, with or without naming it.
    assert location_of(create(w.lim_agent)) == w.north
    assert location_of(create(w.lim_agent, location_id=str(w.north))) == w.north
    # Naming a location outside the caller's scope is a 404.
    assert create(w.lim_agent, location_id=str(w.south)).status_code == 404
    # Two locations: the caller must say which one.
    assert create(w.lim_both).status_code == 422
    assert location_of(create(w.lim_both, location_id=str(w.south))) == w.south
    # Unrestricted callers may leave it organization-wide or name any location of the organization.
    assert location_of(create(w.full_agent)) is None
    assert location_of(create(w.full_agent, location_id=str(w.south))) == w.south
    # Another organization's location is not found.
    other = build_world(v2_app, db, "Other")
    assert create(w.full_agent, location_id=str(other.north)).status_code == 404


def test_merge_and_erase_need_every_conversation_of_the_contact_in_scope(
    v2_app: FastAPI, db: Session
) -> None:
    w = build_world(v2_app, db)
    client = w.lim_admin.client
    headers = csrf_headers(client)
    # Target out of scope: not found. Source with a conversation in another location: refused.
    assert (
        client.post(
            w.url(f"/contacts/{w.contact_north}/merge"),
            params={"target_id": str(w.contact_south)},
            headers=headers,
        ).status_code
        == 404
    )
    assert (
        client.post(
            w.url(f"/contacts/{w.contact_mixed}/merge"),
            params={"target_id": str(w.contact_north)},
            headers=headers,
        ).status_code
        == 403
    )
    assert client.delete(w.url(f"/contacts/{w.contact_mixed}"), headers=headers).status_code == 403
    assert client.delete(w.url(f"/contacts/{w.contact_south}"), headers=headers).status_code == 404
    # A contact whose threads are all in scope can be erased by the limited admin.
    assert client.delete(w.url(f"/contacts/{w.contact_north}"), headers=headers).status_code == 204
    # The unrestricted admin can erase the mixed one.
    assert (
        w.full_admin.client.delete(
            w.url(f"/contacts/{w.contact_mixed}"), headers=csrf_headers(w.full_admin.client)
        ).status_code
        == 204
    )


def test_knowledge_sources_follow_the_callers_locations(v2_app: FastAPI, db: Session) -> None:
    w = build_world(v2_app, db)
    every = (w.source_north, w.source_south, w.source_org)
    assert ids_in(w.full_admin.client.get(w.bot("/sources")), *every) == set(every)
    assert ids_in(w.lim_admin.client.get(w.bot("/sources")), *every) == {w.source_north}
    assert ids_in(w.lim_both.client.get(w.bot("/sources")), *every) == {
        w.source_north,
        w.source_south,
    }
    for hidden in (w.source_south, w.source_org):
        assert w.lim_admin.client.get(w.bot(f"/sources/{hidden}")).status_code == 404
        assert w.full_admin.client.get(w.bot(f"/sources/{hidden}")).status_code == 200
    assert w.lim_admin.client.get(w.bot(f"/sources/{w.source_north}")).status_code == 200
    # Jobs and revisions describe the bot's whole knowledge: unrestricted callers only.
    for path in ("/jobs", "/revisions"):
        assert w.lim_admin.client.get(w.bot(path)).status_code == 403, path
        assert w.full_admin.client.get(w.bot(path)).status_code == 200, path
    assert w.lim_admin.client.get(w.bot("/documents")).status_code == 200
    assert w.lim_admin.client.get(w.bot("/documents")).json() == []


def test_channel_list_follows_the_callers_locations(v2_app: FastAPI, db: Session) -> None:
    w = build_world(v2_app, db)

    def names(person: Person) -> set[str]:
        response = person.client.get(w.url("/channels"))
        assert response.status_code == 200, response.text
        return {item["display_name"] for item in response.json()["items"]}

    assert names(w.full_agent) == {"North line", "South line", "Org line"}
    assert names(w.lim_agent) == {"North line"}
    assert names(w.lim_both) == {"North line", "South line"}


def test_analytics_by_bot_follow_the_callers_locations(v2_app: FastAPI, db: Session) -> None:
    w = build_world(v2_app, db)
    full = w.full_admin.client.get(w.bot("/analytics/summary")).json()
    limited = w.lim_admin.client.get(w.bot("/analytics/summary")).json()
    both = w.lim_both.client.get(w.bot("/analytics/summary")).json()
    # Five conversations exist (north, south, org line, website, mixed-south), one message each.
    assert (full["conversations"], full["messages"], full["leads"]) == (5, 5, 5)
    assert (limited["conversations"], limited["messages"], limited["leads"]) == (1, 1, 1)
    assert (both["conversations"], both["messages"], both["leads"]) == (3, 3, 3)
    assert limited["handoffs"] == 0 and full["handoffs"] == 1  # the org-line thread waits
    volume = w.lim_admin.client.get(w.bot("/analytics/volume")).json()["days"]
    assert sum(day["visitor"] for day in volume) == 1
    full_volume = w.full_admin.client.get(w.bot("/analytics/volume")).json()["days"]
    assert sum(day["visitor"] for day in full_volume) == 5
    top = w.lim_admin.client.get(w.bot("/analytics/top-questions")).json()["questions"]
    assert {item["question"] for item in top} == {"north question"}
    leads = w.lim_admin.client.get(w.bot("/analytics/leads")).json()
    assert sum(day["leads"] for day in leads["trend"]) == 1
    assert (
        sum(
            day["leads"]
            for day in w.full_admin.client.get(w.bot("/analytics/leads")).json()["trend"]
        )
        == 5
    )
    csv_limited = w.lim_admin.client.get(w.bot("/analytics/conversations.csv"))
    assert csv_limited.status_code == 200
    assert str(w.conv_north) in csv_limited.text
    for hidden in (w.conv_south, w.conv_org, w.conv_web):
        assert str(hidden) not in csv_limited.text
    assert str(w.conv_web) in w.full_admin.client.get(w.bot("/analytics/conversations.csv")).text
    # Leads CSV only lists contacts in the caller's locations.
    leads_csv = w.lim_admin.client.get(w.bot("/analytics/leads.csv"))
    assert leads_csv.status_code == 200
    assert "south" not in leads_csv.text.lower() and "org-" not in leads_csv.text.lower()


def test_organization_analytics_follow_the_callers_locations(v2_app: FastAPI, db: Session) -> None:
    w = build_world(v2_app, db)
    base = w.url("/analytics")
    # Website-only default: the website conversation is organization-wide.
    assert w.full_admin.client.get(base).json()["total_conversations"] == 1
    assert w.lim_admin.client.get(base).json()["total_conversations"] == 0
    both = w.full_admin.client.get(base, params={"channel": "whatsapp"}).json()
    one = w.lim_admin.client.get(base, params={"channel": "whatsapp"}).json()
    two = w.lim_both.client.get(base, params={"channel": "whatsapp"}).json()
    assert (
        both["total_conversations"],
        one["total_conversations"],
        two["total_conversations"],
    ) == (
        4,
        1,
        3,
    )
    assert one["handoff_count"] == 0 and both["resolved_vs_open"]["open"] == 4
    breakdown = {row["channel"]: row["conversations"] for row in one["channel_breakdown"]}
    assert breakdown == {"whatsapp": 1}
    all_breakdown = {row["channel"]: row["conversations"] for row in both["channel_breakdown"]}
    assert all_breakdown == {"website": 1, "whatsapp": 4}
    today = datetime.now(UTC).date()
    series = w.lim_admin.client.get(
        w.url("/analytics/timeseries"),
        params={"from": (today - timedelta(days=1)).isoformat(), "to": today.isoformat()},
    ).json()["days"]
    assert sum(day["conversations"] for day in series) == 0  # website only, hidden from limited
    full_series = w.full_admin.client.get(
        w.url("/analytics/timeseries"),
        params={"from": (today - timedelta(days=1)).isoformat(), "to": today.isoformat()},
    ).json()["days"]
    assert sum(day["conversations"] for day in full_series) == 1


def test_follow_ups_follow_the_callers_locations(v2_app: FastAPI, db: Session) -> None:
    w = build_world(v2_app, db)
    when = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    db.add(
        FollowUp(
            id=uuid4(),
            tenant_id=w.tenant_id,
            bot_id=w.bot_id,
            conversation_id=w.conv_web,
            text="later",
            send_at=datetime.now(UTC) + timedelta(days=1),
            status="scheduled",
        )
    )
    db.commit()
    assert len(w.full_agent.client.get(w.url("/follow-ups")).json()["follow_ups"]) == 1
    assert w.lim_agent.client.get(w.url("/follow-ups")).json()["follow_ups"] == []
    created = w.lim_agent.client.post(
        w.url("/follow-ups"),
        json={"conversation_id": str(w.conv_web), "text": "hi", "send_at": when},
        headers=csrf_headers(w.lim_agent.client),
    )
    assert created.status_code == 404


def test_other_organizations_are_invisible_to_everyone(v2_app: FastAPI, db: Session) -> None:
    a = build_world(v2_app, db, "Alpha")
    b = build_world(v2_app, db, "Bravo")
    for person in (a.full_admin, a.lim_admin):
        # Another tenant's resources under this tenant's URL, and this person under that URL.
        assert person.client.get(a.url(f"/conversations/{b.conv_north}")).status_code == 404
        assert person.client.get(a.url(f"/contacts/{b.contact_north}")).status_code == 404
        assert person.client.get(a.bot(f"/sources/{b.source_north}")).status_code == 404
        assert person.client.get(b.url("/inbox")).status_code == 404
        assert person.client.get(b.url("/contacts")).status_code == 404
    # The two worlds do not leak into each other's lists.
    everything_b = (b.conv_north, b.conv_south, b.conv_org, b.conv_web)
    assert ids_in(a.full_admin.client.get(a.url("/inbox")), *everything_b) == set()
    assert ids_in(a.lim_both.client.get(a.url("/inbox")), *everything_b) == set()
    assert (
        ids_in(a.full_admin.client.get(a.url("/contacts")), b.contact_north, b.contact_org) == set()
    )
    assert b.north not in {
        row
        for row in db.scalars(
            select(MembershipLocation.location_id).where(
                MembershipLocation.tenant_id == a.tenant_id
            )
        )
    }


def test_flag_off_ignores_scope_and_location_fields(app: FastAPI, db: Session) -> None:
    """With IDENTITY_V2_ENABLED off nothing here changes: legacy roles, no location filter."""
    w = build_world(app, db)
    every = (w.conv_north, w.conv_south, w.conv_org, w.conv_web)
    # The membership says limited, but the flag is off: the legacy path shows everything.
    assert ids_in(w.lim_agent.client.get(w.url("/inbox")), *every) == set(every)
    assert w.lim_agent.client.get(w.url(f"/contacts/{w.contact_south}")).status_code == 200
    # A location_id in a contact body is ignored while the flag is off.
    created = w.full_agent.client.post(
        w.url("/contacts"),
        json={
            "display_name": "Plain",
            "email": f"p-{uuid4().hex[:8]}@example.com",
            "location_id": str(w.north),
        },
        headers=csrf_headers(w.full_agent.client),
    )
    assert created.status_code == 201
    assert (
        db.scalar(select(Contact.location_id).where(Contact.id == UUID(created.json()["id"])))
        is None
    )
