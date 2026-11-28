# ruff: noqa: F811
"""Phase 5C: one erasure request for one person, in the SaaS and in Many. A fake Many answers.

Covers: both sides end empty on test data, the Many call carries the same request id and nothing
extra, idempotent repeats, a Many failure that leaves the SaaS erased and is retried to the end,
failure reasons, roles, flag off, tenant isolation, and that no identifier is left behind.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.chat.conversations import append_message
from app.core.config import get_settings
from app.db.models import AuditEvent, Contact, Conversation, ErasureCase, Message
from app.identity import many_proxy
from tests.identity_helpers import build_org
from tests.test_customer_links import (  # type: ignore[attr-defined]  # noqa: F401
    FakeMany,
    _connection,
    _identity,
    _lead,
    _links,
    _map,
    _ok,
    _sync,
    _world,
    many,
    proxy_settings,
    uni_app,
)
from tests.test_phase3_review_fixes import _limit_to_a_new_location

ERASED = many_proxy.ManyResponse(
    202,
    {"content-type": "application/json"},
    json.dumps({"event_id": "evt-1", "local_status": "erased", "remote_status": "queued"}).encode(),
)


def _answer(status: int) -> many_proxy.ManyResponse:
    return many_proxy.ManyResponse(status, {"content-type": "application/json"}, b'{"detail":"x"}')


def _chat(db: Session, users: Any, connection: Any, contact: Contact) -> Conversation:
    conversation = Conversation(
        tenant_id=users.tenant_id,
        bot_id=connection.bot_id,
        source="channel",
        channel="whatsapp",
        connection_id=connection.id,
        contact_id=contact.id,
        external_conversation_id=f"conv-{uuid4().hex[:8]}",
        mode="human",
        status="open",
    )
    db.add(conversation)
    db.commit()
    append_message(db, conversation, sender_type="ai", text="SECRET-REPLY-TEXT", can_answer=True)
    db.commit()
    return conversation


def _filled(uni_app: FastAPI, db: Session, many: FakeMany, label: str) -> tuple[Any, ...]:
    users, w1, w2, f1 = _world(uni_app, db, label)
    connection = _connection(db, users, "whatsapp", w1)
    contact = _identity(db, users, connection, "whatsapp", "SECRET-EXT-U1")
    _chat(db, users, connection, contact)
    db.commit()
    leads = [
        _lead("whatsapp", w1, "SECRET-EXT-U1"),  # linked, has chat data
        _lead("whatsapp", w2, "SECRET-EXT-U2"),  # many_only, no SaaS data
    ]
    assert _sync(users, many, [w1, w2], [f1], leads).status_code == 200
    return users, w1, w2, contact


def _link(db: Session, users: Any, state: str, channel: str) -> Any:
    return next(
        r for r in _links(db, users.tenant_id) if r.state == state and r.many_channel_id == channel
    )


def _erase(users: Any, link_id: Any, request_id: UUID | None = None, role: str = "admin") -> Any:
    return users.call(
        role,
        "POST",
        f"/api/v1/tenants/{users.tenant_id}/customer-links/{link_id}/erase",
        json={"request_id": str(request_id or uuid4())},
    )


def _privacy_calls(many: FakeMany) -> list[dict[str, Any]]:
    return [c for c in many.forwarded if c["path"].startswith("/privacy/contact-erasure/")]


def _nothing_left(db: Session, tenant_id: UUID, *needles: str) -> None:
    tables = (
        "customer_links",
        "erasure_cases",
        "contacts",
        "contact_identities",
        "conversations",
        "messages",
        "audit_events",
    )
    for table in tables:
        for row in db.execute(text(f"SELECT * FROM {table}")).all():  # noqa: S608
            blob = " ".join(str(v) for v in row)
            for needle in needles:
                assert needle not in blob, (table, needle)


# --- the whole flow ---------------------------------------------------------------------------


def test_erasing_a_linked_person_empties_both_sides(
    uni_app: FastAPI, db: Session, many: FakeMany
) -> None:
    users, w1, _w2, contact = _filled(uni_app, db, many, "ce-both")
    contact_id = contact.id
    link = _link(db, users, "linked", w1)
    many.plan.append(ERASED)
    request_id = uuid4()
    response = _erase(users, link.id, request_id)
    assert response.status_code == 202, response.text
    assert response.json()["state"] == "complete"
    # SaaS side: contact, identities, conversation and messages are gone.
    db.expire_all()
    assert db.scalar(select(func.count(Contact.id)).where(Contact.id == contact_id)) == 0
    assert db.scalar(select(func.count(Conversation.id))) == 0
    assert db.scalar(select(func.count(Message.id))) == 0
    # Many side: asked once, with this request id and the identity, for the right channel.
    (call,) = _privacy_calls(many)
    assert call["path"] == f"/privacy/contact-erasure/whatsapp/{w1}"
    assert json.loads(call["body"]) == {
        "request_id": str(request_id),
        "external_contact_id": "SECRET-EXT-U1",
    }
    headers = {k.lower(): v for k, v in call["headers"].items()}
    assert headers["authorization"].startswith("Bearer many-token-")
    assert "cookie" not in headers
    # The link is erased and scrubbed; the case is complete.
    db.expire_all()
    row = db.get(type(link), link.id)
    assert row is not None
    assert (row.state, row.external_id, row.display_name, row.many_lead_id, row.contact_id) == (
        "erased",
        None,
        None,
        None,
        None,
    )
    case = db.scalar(select(ErasureCase))
    assert case is not None and case.state == "complete" and case.many_event_id == "evt-1"
    # No identifier or message text is left anywhere we wrote, audit included.
    _nothing_left(db, users.tenant_id, "SECRET-EXT-U1", "SECRET-REPLY-TEXT")
    actions = {a.action for a in db.scalars(select(AuditEvent))}
    assert {
        "customer_erasure.requested",
        "customer_erasure.saas_erased",
        "customer_erasure.complete",
    } <= actions


def test_a_person_known_only_to_many_is_erased_in_many(
    uni_app: FastAPI, db: Session, many: FakeMany
) -> None:
    users, _w1, w2, _contact = _filled(uni_app, db, many, "ce-many-only")
    link = _link(db, users, "many_only", w2)
    many.plan.append(ERASED)
    response = _erase(users, link.id)
    assert response.json()["state"] == "complete"
    (call,) = _privacy_calls(many)
    assert call["path"] == f"/privacy/contact-erasure/whatsapp/{w2}"
    assert json.loads(call["body"])["external_contact_id"] == "SECRET-EXT-U2"
    db.expire_all()
    other = db.get(type(link), link.id)
    assert other is not None and other.external_id is None
    # The other person is untouched.
    assert db.scalar(select(func.count(Contact.id))) == 1


def test_the_same_request_id_changes_nothing_a_second_time(
    uni_app: FastAPI, db: Session, many: FakeMany
) -> None:
    users, w1, _w2, _c = _filled(uni_app, db, many, "ce-idem")
    link = _link(db, users, "linked", w1)
    many.plan.append(ERASED)
    request_id = uuid4()
    first = _erase(users, link.id, request_id).json()
    second = _erase(users, link.id, request_id).json()
    assert first["id"] == second["id"] and second["state"] == "complete"
    assert len(_privacy_calls(many)) == 1
    assert db.scalar(select(func.count(ErasureCase.id))) == 1
    again = _erase(users, link.id)  # a new request for an erased person
    assert again.status_code == 409 and again.json()["error"]["code"] == "ALREADY_ERASED"


# --- Many failing -----------------------------------------------------------------------------


def test_many_down_leaves_the_saas_erased_and_a_retry_finishes_it(
    uni_app: FastAPI, db: Session, many: FakeMany
) -> None:
    users, w1, _w2, contact = _filled(uni_app, db, many, "ce-retry")
    contact_id = contact.id
    link = _link(db, users, "linked", w1)
    many.plan.append(many_proxy.ManyUnavailable("down"))
    request_id = uuid4()
    first = _erase(users, link.id, request_id)
    assert first.status_code == 202
    body = first.json()
    assert body["state"] == "needs_action" and body["reason"] == "many_unavailable"
    assert "try again" in body["message"].lower()
    db.expire_all()
    assert db.scalar(select(func.count(Contact.id)).where(Contact.id == contact_id)) == 0
    held = db.get(type(link), link.id)
    assert held is not None
    assert held.state == "erased" and held.external_id == "SECRET-EXT-U1"  # kept for the retry
    many.plan.append(ERASED)
    retried = users.call(
        "admin", "POST", f"/api/v1/tenants/{users.tenant_id}/erasure-cases/{body['id']}/retry"
    )
    assert retried.status_code == 202 and retried.json()["state"] == "complete"
    sent = [json.loads(c["body"])["request_id"] for c in _privacy_calls(many)]
    assert sent == [str(request_id), str(request_id)]  # the same id both times
    db.expire_all()
    done = db.get(type(link), link.id)
    assert done is not None and done.external_id is None
    listed = users.call("admin", "GET", f"/api/v1/tenants/{users.tenant_id}/erasure-cases").json()
    assert [c["state"] for c in listed["items"]] == ["complete"]


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (404, "many_channel_not_found"),
        (403, "many_forbidden"),
        (429, "many_rate_limited"),
        (500, "many_unavailable"),
    ],
)
def test_many_refusals_become_a_plain_reason(
    uni_app: FastAPI, db: Session, many: FakeMany, status: int, reason: str
) -> None:
    users, w1, _w2, _c = _filled(uni_app, db, many, f"ce-{status}")
    link = _link(db, users, "linked", w1)
    many.plan.append(_answer(status))
    body = _erase(users, link.id).json()
    assert body["state"] == "needs_action" and body["reason"] == reason and body["message"]
    assert "detail" not in json.dumps(body)  # Many's body is never passed on


def test_an_unusable_many_answer_is_not_called_complete(
    uni_app: FastAPI, db: Session, many: FakeMany
) -> None:
    users, w1, _w2, _c = _filled(uni_app, db, many, "ce-odd")
    link = _link(db, users, "linked", w1)
    many.plan.append(_ok({"local_status": "not-erased"}))
    assert _erase(users, link.id).json()["reason"] == "many_answer_unusable"


# --- who may, flag, isolation -----------------------------------------------------------------


def test_only_owner_or_admin_may_erase_and_the_flag_gates_it(
    uni_app: FastAPI, db: Session, many: FakeMany
) -> None:
    users, w1, _w2, _c = _filled(uni_app, db, many, "ce-roles")
    link = _link(db, users, "linked", w1)
    for role in ("editor", "viewer"):
        assert _erase(users, link.id, role=role).status_code == 403, role
    assert _privacy_calls(many) == []
    uni_app.dependency_overrides[get_settings] = lambda: proxy_settings()  # flag off
    assert _erase(users, link.id).status_code == 404


def test_a_location_limited_admin_may_not_erase(
    uni_app: FastAPI, db: Session, many: FakeMany
) -> None:
    org = build_org(uni_app, db, "CeLoc")
    admin = org.people["admin"]
    _limit_to_a_new_location(db, org.tenant_id, admin.user_id)
    response = admin.client.get(f"/api/v1/tenants/{org.tenant_id}/erasure-cases")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "LOCATION_SCOPE_UNSUPPORTED"


def test_one_organization_cannot_erase_or_see_anothers_people(
    uni_app: FastAPI, db: Session, many: FakeMany
) -> None:
    a, w1, _w2, _c = _filled(uni_app, db, many, "ce-iso-a")
    b, *_ = _world(uni_app, db, "ce-iso-b")
    link = _link(db, a, "linked", w1)
    assert _erase(b, link.id).status_code == 404
    assert _privacy_calls(many) == []
    assert b.call("admin", "GET", f"/api/v1/tenants/{b.tenant_id}/erasure-cases").json() == {
        "items": []
    }
    many.plan.append(ERASED)
    case = _erase(a, link.id).json()
    retry = b.call(
        "admin", "POST", f"/api/v1/tenants/{b.tenant_id}/erasure-cases/{case['id']}/retry"
    )
    assert retry.status_code == 404


def test_a_request_id_cannot_be_reused_for_another_person(
    uni_app: FastAPI, db: Session, many: FakeMany
) -> None:
    users, w1, w2, _c = _filled(uni_app, db, many, "ce-reuse")
    one, two = _link(db, users, "linked", w1), _link(db, users, "many_only", w2)
    many.plan.append(ERASED)
    request_id = uuid4()
    assert _erase(users, one.id, request_id).status_code == 202
    clash = _erase(users, two.id, request_id)
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "REQUEST_ID_REUSED"


def test_a_missing_identity_asks_for_a_sync_first(
    uni_app: FastAPI, db: Session, many: FakeMany
) -> None:
    users, w1, _w2, _c = _filled(uni_app, db, many, "ce-noid")
    link = _link(db, users, "linked", w1)
    link.external_id = None
    db.commit()
    response = _erase(users, link.id)
    assert (
        response.status_code == 409 and response.json()["error"]["code"] == "IDENTITY_UNAVAILABLE"
    )
    assert _privacy_calls(many) == []


def test_the_link_lists_never_carry_the_raw_identity(
    uni_app: FastAPI, db: Session, many: FakeMany
) -> None:
    users, *_ = _filled(uni_app, db, many, "ce-hide")
    body = users.call("admin", "GET", f"/api/v1/tenants/{users.tenant_id}/customer-links").text
    assert "SECRET-EXT" not in body
