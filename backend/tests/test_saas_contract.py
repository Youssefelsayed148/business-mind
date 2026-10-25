"""M-07: contract tests of Many's delegated mode against a FAKE SaaS
(tests/fake_saas.py). The fake checks signatures/envelopes independently of
Many's code, records every request and answers from a script. Nothing here
touches the network, Meta or OpenAI."""

import copy
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest

from app.api.routes_auth import get_current_user
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.saas_forward_event import SaasForwardEvent
from app.models.saas_outbound_message import SaasOutboundMessage
from app.integrations.meta.messaging import MetaMessageResult
from app.integrations.meta.whatsapp_webhooks import ParsedWhatsappStatusEvent
from app.services import saas_delegation_service as delegation
from app.services import saas_forwarder as fwd
from app.services import saas_health, saas_outbound
from app.services.whatsapp_webhook_service import process_whatsapp_status_events
from tests import fake_saas
from tests.conftest import skip_if_no_db
from tests.fake_saas import FakeSaas
from tests.test_saas_delegation_config import _user
from tests.test_saas_delegation_dispatch import (  # noqa: F401
    _env, _fb_page, _ig_account, _run, _wa_account, fb_payload, ig_payload, wa_payload,
)
from tests.test_saas_messages import CONN, OLD_SECRET, SECRET, _world, _accept, clients  # noqa: F401


@pytest.fixture
def saas():
    return FakeSaas("conn-1", [SECRET])


def _deliver(db, key, fake, **kw):
    return fwd.process_ordering_key(db, key, client=fake.client(), **kw)


def _events(db, channel, event_type=None):
    db.expire_all()
    q = db.query(SaasForwardEvent).filter_by(channel_id=channel.id)
    if event_type:
        q = q.filter_by(event_type=event_type)
    return q.order_by(SaasForwardEvent.seq).all()


def _conv(db, **kw):
    return db.query(Conversation).filter_by(**kw).one()


# --- inbound: delegation on / off ----------------------------------------------------


@skip_if_no_db
def test_delegation_on_dm_reaches_the_saas_signed_and_ai_never_runs(db_session, saas):
    acc = _wa_account(db_session, delegated=True, ai_enabled=False)  # ai_enabled=False is irrelevant
    result = _run(db_session, wa_payload(acc, "16315551234", "hello", "wamid.c1"), "whatsapp_business_account")
    conv = _conv(db_session, whatsapp_account_id=acc.id)
    assert not result.ai_touched
    assert _deliver(db_session, str(conv.id), saas).sent == 1
    [req] = saas.requests
    assert req.path == fwd.EVENTS_PATH and req.signature_ok and saas.problems == []
    [p] = saas.delivered("message.received")
    assert p["channel"] == "whatsapp" and p["text"] == "hello" and p["connection_id"] == "conn-1"
    assert p["external_conversation_id"] == str(conv.id) and p["external_message_id"] == "wamid.c1"


@skip_if_no_db
def test_delegation_off_is_todays_behaviour_and_sends_nothing(db_session, saas):
    acc = _wa_account(db_session, delegated=False, ai_enabled=True)
    result = _run(db_session, wa_payload(acc, "16315551234", "hello", "wamid.c2"), "whatsapp_business_account")
    assert result.wa_turn.delay.called  # Many's own AI turn is dispatched exactly as before
    assert _events(db_session, acc) == [] and saas.requests == []


@skip_if_no_db
@pytest.mark.parametrize("which", ["ig_echo", "ig_postback", "ig_quick_reply", "fb_echo", "fb_postback", "wa_reaction", "wa_stop"])
def test_automation_traffic_is_not_forwarded(db_session, saas, which):
    if which.startswith("ig"):
        acc = _ig_account(db_session, delegated=True)
        payload, kind = ig_payload(acc.ig_user_id, "9000011", "hi", "mid.a1"), "instagram"
        msg = payload["entry"][0]["messaging"][0]
    elif which.startswith("fb"):
        acc = _fb_page(db_session, delegated=True)
        payload, kind = fb_payload(acc.page_id, "psid-1", "hi", "mid.a1"), "page"
        msg = payload["entry"][0]["messaging"][0]
    else:
        acc = _wa_account(db_session, delegated=True)
        payload, kind = wa_payload(acc, "16315551234", "STOP" if which == "wa_stop" else "x", "wamid.a1"), "whatsapp_business_account"
        msg = payload["entry"][0]["changes"][0]["value"]["messages"][0]
    if which.endswith("echo"):
        msg["message"]["is_echo"] = True
    elif which == "ig_quick_reply":
        msg["message"]["quick_reply"] = {"payload": "FOLLOW_CHECK"}
    elif which.endswith("postback"):
        msg.pop("message")
        msg["postback"] = {"mid": "mid.pb", "payload": "FOLLOW_CHECK"}
    elif which == "wa_reaction":
        msg.pop("text")
        msg["type"] = "reaction"
    result = _run(db_session, payload, kind)
    assert _events(db_session, acc, "message.received") == [] and not result.ai_touched


@skip_if_no_db
def test_whatsapp_receipts_are_not_forwarded_as_inbound(db_session, saas):
    w = _world(db_session)
    process_whatsapp_status_events(db_session, [ParsedWhatsappStatusEvent(
        phone_number_id=w.channel.phone_number_id, provider_message_id="wamid.unknown", status="read",
        timestamp="1700000100", recipient_wa_id=w.contact_id, conversation=None, pricing=None, errors=[], raw_event={},
    )])
    assert _events(db_session, w.channel) == []


# --- SaaS down: no fallback, retry/backoff/dedupe/order ---------------------------------


@skip_if_no_db
def test_saas_down_queues_retries_same_event_id_and_never_falls_back_to_ai(db_session, saas):
    acc = _wa_account(db_session, delegated=True, ai_enabled=True)
    result = _run(db_session, wa_payload(acc, "16315551234", "hello", "wamid.d1"), "whatsapp_business_account")
    key = str(_conv(db_session, whatsapp_account_id=acc.id).id)
    saas.down = True
    t0 = datetime.now(timezone.utc)
    first = _deliver(db_session, key, saas, now=t0)
    assert first.sent == 0 and first.retry_in and first.retry_in > 0
    db_session.refresh(acc)
    assert acc.saas_degraded is True and acc.saas_last_forward_status == "retrying"
    [event] = _events(db_session, acc, "message.received")
    assert event.status == "pending" and event.attempts == 1 and event.payload  # still queued, payload kept
    # not due yet -> no extra request
    assert _deliver(db_session, key, saas, now=t0).sent == 0 and len(saas.requests) == 1
    # recovery: same event_id, delivered once, degraded clears
    saas.down = False
    assert _deliver(db_session, key, saas, now=t0 + timedelta(hours=1)).sent == 1
    assert {r.payload["event_id"] for r in saas.requests} == {"in:whatsapp:wamid.d1"}
    db_session.refresh(acc)
    assert acc.saas_degraded is False
    assert not result.ai_touched and not result.generate.called


@skip_if_no_db
def test_5xx_then_429_retry_after_then_success(db_session, saas):
    acc = _wa_account(db_session, delegated=True)
    _run(db_session, wa_payload(acc, "16315551234", "hello", "wamid.r1"), "whatsapp_business_account")
    key = str(_conv(db_session, whatsapp_account_id=acc.id).id)
    saas.respond(httpx.Response(503), httpx.Response(429, headers={"Retry-After": "120"}))
    t = datetime.now(timezone.utc)
    r1 = _deliver(db_session, key, saas, now=t)
    assert r1.retry_in and 2 <= r1.retry_in <= 10  # first backoff ~5s with jitter
    t += timedelta(seconds=r1.retry_in + 1)
    r2 = _deliver(db_session, key, saas, now=t)
    assert r2.retry_in >= 120  # Retry-After honoured
    t += timedelta(seconds=r2.retry_in + 1)
    assert _deliver(db_session, key, saas, now=t).sent == 1
    assert saas.attempts_for("in:whatsapp:wamid.r1") == 3


@skip_if_no_db
def test_other_4xx_is_not_retried_and_queue_continues(db_session, saas):
    acc = _wa_account(db_session, delegated=True)
    _run(db_session, wa_payload(acc, "16315551234", "one", "wamid.f1"), "whatsapp_business_account")
    _run(db_session, wa_payload(acc, "16315551234", "two", "wamid.f2"), "whatsapp_business_account")
    key = str(_conv(db_session, whatsapp_account_id=acc.id).id)
    saas.respond(httpx.Response(422, json={"detail": "malformed"}))
    res = _deliver(db_session, key, saas)
    assert res.failed == 1 and res.sent == 1
    assert saas.attempts_for("in:whatsapp:wamid.f1") == 1  # never retried
    assert [e.status for e in _events(db_session, acc, "message.received")] == ["failed", "sent"]


@skip_if_no_db
def test_a_retrying_event_blocks_later_events_of_the_same_conversation_only(db_session, saas):
    acc = _wa_account(db_session, delegated=True)
    _run(db_session, wa_payload(acc, "16315551234", "one", "wamid.o1"), "whatsapp_business_account")
    _run(db_session, wa_payload(acc, "16315551234", "two", "wamid.o2"), "whatsapp_business_account")
    _run(db_session, wa_payload(acc, "16315559999", "other", "wamid.o3"), "whatsapp_business_account")
    keys = {c.lead_id: str(c.id) for c in db_session.query(Conversation).filter_by(whatsapp_account_id=acc.id)}
    k1, k2 = sorted(keys.values(), key=lambda k: db_session.query(SaasForwardEvent).filter_by(ordering_key=k).count(), reverse=True)
    saas.respond(httpx.Response(500))
    t = datetime.now(timezone.utc)
    assert _deliver(db_session, k1, saas, now=t).sent == 0
    assert [p["event_id"] for p in saas.delivered()] == []  # "two" did not overtake "one"
    assert _deliver(db_session, k2, saas, now=t).sent == 1  # another conversation is unaffected
    assert _deliver(db_session, k1, saas, now=t + timedelta(minutes=1)).sent == 2
    assert [p["event_id"] for p in saas.delivered()] == ["in:whatsapp:wamid.o3", "in:whatsapp:wamid.o1", "in:whatsapp:wamid.o2"]


@skip_if_no_db
def test_duplicate_acknowledged_by_the_saas_is_success_and_never_resent(db_session, saas):
    acc = _wa_account(db_session, delegated=True)
    _run(db_session, wa_payload(acc, "16315551234", "hello", "wamid.dup"), "whatsapp_business_account")
    key = str(_conv(db_session, whatsapp_account_id=acc.id).id)
    saas.seen.add(("conn-1", "in:whatsapp:wamid.dup"))
    assert _deliver(db_session, key, saas).sent == 1
    assert _deliver(db_session, key, saas).sent == 0 and len(saas.requests) == 1


@skip_if_no_db
def test_retry_budget_exhaustion_fails_the_event_and_marks_degraded(db_session, saas):
    acc = _wa_account(db_session, delegated=True)
    _run(db_session, wa_payload(acc, "16315551234", "hello", "wamid.b1"), "whatsapp_business_account")
    key = str(_conv(db_session, whatsapp_account_id=acc.id).id)
    saas.down = True
    res = _deliver(db_session, key, saas, now=datetime.now(timezone.utc) + timedelta(hours=25))
    assert res.failed == 1
    db_session.refresh(acc)
    assert acc.saas_degraded is True and acc.saas_last_forward_status == "retry_budget_exhausted"


# --- signing: events Many sends, calls Many receives ---------------------------------------


@skip_if_no_db
def test_events_carry_the_contract_headers_and_envelope(db_session, saas):
    acc = _wa_account(db_session, delegated=True)
    _run(db_session, wa_payload(acc, "16315551234", "hello", "wamid.h1"), "whatsapp_business_account")
    _deliver(db_session, str(_conv(db_session, whatsapp_account_id=acc.id).id), saas)
    [req] = saas.requests
    h = {k.lower(): v for k, v in req.headers.items()}
    assert h["x-osiris-connection"] == "conn-1" and h["x-osiris-signature"].startswith("sha256=")
    assert h["x-osiris-timestamp"].isdigit() and h["content-type"].startswith("application/json")
    assert req.signature_ok and saas.problems == []


def _post_many(client, w, body: dict | None = None, *, secret=SECRET, connection=CONN, now=None, raw=None, drop=()):
    data = body or {"message_id": f"m-{uuid4().hex[:8]}", "connection_id": connection,
                    "external_contact_id": w.contact_id, "external_conversation_id": str(w.conv.id),
                    "text": "Hello", "kind": "reply"}
    raw = raw if raw is not None else json.dumps(data, separators=(",", ":")).encode()
    headers = fake_saas.sign(connection, secret, raw, now=now)
    for h in drop:
        headers.pop(h)
    return client.post("/api/saas/messages", content=raw, headers=headers)


@pytest.fixture
def started():
    with patch("app.api.routes_saas_messages._start_delivery") as start:
        yield start


@skip_if_no_db
def test_signature_rejection_matrix_is_one_generic_401(client, db_session, started):
    import time

    w = _world(db_session)
    off = _world(db_session, connection="conn-off")
    off.channel.saas_delegation_enabled = False
    db_session.commit()
    big = json.dumps({"message_id": "x", "text": "a" * 70000}).encode()
    cases = {
        "wrong secret": _post_many(client, w, secret="z" * 40),
        "stale timestamp": _post_many(client, w, now=time.time() - 301),
        "future timestamp": _post_many(client, w, now=time.time() + 301),
        "missing signature": _post_many(client, w, drop=("X-Osiris-Signature",)),
        "missing timestamp": _post_many(client, w, drop=("X-Osiris-Timestamp",)),
        "missing connection": _post_many(client, w, drop=("X-Osiris-Connection",)),
        "unknown connection": _post_many(client, w, connection="nope"),
        "delegation off": _post_many(client, w, connection="conn-off"),
        "oversize body": _post_many(client, w, raw=big),
    }
    tampered = fake_saas.sign(CONN, SECRET, b'{"a":1}')
    cases["tampered body"] = client.post("/api/saas/messages", content=b'{"a":2}', headers=tampered)
    for name, resp in cases.items():
        assert resp.status_code == 401 and resp.json() == {"detail": "unauthorized"}, name
    assert not started.called


@skip_if_no_db
def test_dual_secret_rotation_both_directions(client, db_session, saas, started):
    w = _world(db_session)
    delegation.set_secret(w.channel, "n" * 40)  # SECRET -> previous (24 h grace)
    db_session.commit()
    # Many accepts either secret inbound...
    assert _post_many(client, w, secret=SECRET).status_code == 202
    assert _post_many(client, w, secret="n" * 40).status_code == 202
    # ...and signs outbound with the NEW one only.
    fresh = FakeSaas("conn-1", ["n" * 40])
    saas_event = saas_health.sync_channel(db_session, "whatsapp", w.channel, force=True, kick=False)
    assert saas_event
    _deliver(db_session, f"channel:whatsapp:{w.channel.id}", fresh)
    assert fresh.requests and all(r.signature_ok for r in fresh.requests)
    old_only = FakeSaas("conn-1", [SECRET])
    w.channel.saas_last_health_at = None
    db_session.commit()
    saas_health.sync_channel(db_session, "whatsapp", w.channel, force=True, kick=False)
    _deliver(db_session, f"channel:whatsapp:{w.channel.id}", old_only)
    assert old_only.requests and not any(r.signature_ok for r in old_only.requests)
    # grace over: the previous secret stops working
    w.channel.saas_previous_secret_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    assert _post_many(client, w, secret=SECRET).status_code == 401


# --- SaaS -> Many sends and status callbacks ----------------------------------------------


def _fail(code, subcode=None):
    err = {"code": code, "message": "localised"}
    if subcode:
        err["error_subcode"] = subcode
    return MetaMessageResult(success=False, error_code="permission_error", error_message="x", raw_response={"error": err})


def _send_via_http(client, db, w, started, text="Hello"):
    mid = f"m-{uuid4().hex[:8]}"
    resp = _post_many(client, w, {"message_id": mid, "connection_id": CONN, "external_contact_id": w.contact_id,
                                  "external_conversation_id": str(w.conv.id), "text": text, "kind": "reply"})
    assert resp.status_code == 202
    row = db.query(SaasOutboundMessage).filter_by(message_id=mid).one()
    return mid, resp.json()["id"], row


@skip_if_no_db
def test_send_is_idempotent_and_the_final_status_arrives_at_the_saas(client, db_session, saas, started, clients):
    w = _world(db_session)
    mid, many_id, row = _send_via_http(client, db_session, w, started)
    again = _post_many(client, w, {"message_id": mid, "connection_id": CONN, "external_contact_id": w.contact_id,
                                   "external_conversation_id": str(w.conv.id), "text": "Hello", "kind": "reply"})
    assert again.status_code == 202 and again.json()["id"] == many_id
    assert db_session.query(SaasOutboundMessage).filter_by(message_id=mid).count() == 1
    assert saas_outbound.deliver_message(db_session, row.message_pk) == "sent"
    assert saas_outbound.deliver_message(db_session, row.message_pk) in ("skipped", "sent")
    assert clients.wa.send_text_message.call_count == 1
    _deliver(db_session, str(w.conv.id), saas)
    [status] = saas.delivered("message.status")
    assert status["message_id"] == mid and status["status"] == "sent" and status["external_message_id"] == "wamid.out"


@skip_if_no_db
@pytest.mark.parametrize(
    "platform, setup, expected",
    [
        ("whatsapp", dict(window_open=False), "window_closed"),
        ("facebook", dict(window_open=False), "window_closed"),
        ("instagram", dict(window_open=False), "window_closed"),
        ("whatsapp", dict(fail=_fail(132000)), "template_required"),
        ("whatsapp", dict(fail=_fail(131026)), "recipient_unreachable"),
        ("facebook", dict(fail=_fail(100, 2018001)), "recipient_unreachable"),
        ("whatsapp", dict(fail=_fail(131056)), "rate_limited"),
        ("whatsapp", dict(fail=_fail(190)), "channel_disconnected"),
        ("whatsapp", dict(text="x" * 5000), "message_too_long"),
        ("instagram", dict(text="é" * 600), "message_too_long"),
    ],
)
def test_failures_reach_the_saas_with_the_contract_error_code(client, db_session, saas, started, clients, platform, setup, expected):
    w = _world(db_session, platform, window_open=setup.get("window_open", True))
    if "fail" in setup:
        for c in (clients.wa, clients.fb, clients.ig):
            c.send_text_message.return_value = setup["fail"]
            c.send_direct_message.return_value = setup["fail"]
    mid, _, row = _send_via_http(client, db_session, w, started, text=setup.get("text", "Hello"))
    assert saas_outbound.deliver_message(db_session, row.message_pk) == "failed"
    _deliver(db_session, str(w.conv.id), saas)
    [status] = saas.delivered("message.status")
    assert status["status"] == "failed" and status["error_code"] == expected and status["message_id"] == mid
    assert len(status.get("error_detail", "")) <= 200 and "localised" not in json.dumps(status)


@skip_if_no_db
def test_whatsapp_delivered_and_read_callbacks_follow_in_order(client, db_session, saas, started, clients):
    w = _world(db_session)
    mid, _, row = _send_via_http(client, db_session, w, started)
    saas_outbound.deliver_message(db_session, row.message_pk)
    for status, ts in (("delivered", "1700000100"), ("read", "1700000200")):
        process_whatsapp_status_events(db_session, [ParsedWhatsappStatusEvent(
            phone_number_id=w.channel.phone_number_id, provider_message_id="wamid.out", status=status,
            timestamp=ts, recipient_wa_id=w.contact_id, conversation=None, pricing=None, errors=[], raw_event={},
        )])
    _deliver(db_session, str(w.conv.id), saas)
    assert [p["status"] for p in saas.delivered("message.status")] == ["sent", "delivered", "read"]


@skip_if_no_db
def test_send_refused_when_the_channel_is_not_delegated(client, db_session, started):
    w = _world(db_session)
    w.channel.saas_delegation_enabled = False
    db_session.commit()
    assert _post_many(client, w).status_code == 401 and not started.called


# --- health ---------------------------------------------------------------------------------


@skip_if_no_db
def test_health_push_heartbeat_and_signed_pull(client, db_session, saas):
    w = _world(db_session)
    t = datetime.now(timezone.utc)
    key = f"channel:whatsapp:{w.channel.id}"
    saas_health.sync_channel(db_session, "whatsapp", w.channel, now=t, kick=False)
    saas_health.sync_channel(db_session, "whatsapp", w.channel, now=t + timedelta(hours=5, minutes=1), kick=False)
    _deliver(db_session, key, saas, now=t + timedelta(hours=6))
    pushed = saas.delivered("channel.status")
    assert len(pushed) == 2 and all(p["status"] in {"token_expired", "connected"} for p in pushed)
    # the pull: empty body, signature over "timestamp."
    headers = fake_saas.sign(CONN, SECRET, b"")
    resp = client.get(f"/api/saas/connections/{CONN}/health", headers=headers)
    assert resp.status_code == 200 and resp.json()["status"] == pushed[-1]["status"] and resp.json()["checked_at"]
    assert client.get(f"/api/saas/connections/{CONN}/health", headers={**headers, "X-Osiris-Signature": "sha256=00"}).status_code == 401


# --- Take Over blocked, rollback --------------------------------------------------------------


@skip_if_no_db
def test_take_over_is_blocked_on_a_delegated_channel(client, db_session):
    from app.main import app

    w = _world(db_session)
    app.dependency_overrides[get_current_user] = lambda: _user(db_session, "admin")
    try:
        for action in ("take-over", "resume-bot"):
            resp = client.post(f"/conversations/{w.conv.id}/{action}")
            assert resp.status_code == 409 and resp.json()["detail"]["code"] == "CHANNEL_MANAGED_BY_SAAS"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@skip_if_no_db
def test_rollback_disabling_delegation_drops_queue_and_restores_old_behaviour(db_session, saas):
    from app.api.routes_saas_delegation import _update
    from app.schemas.saas_delegation import SaasDelegationUpdate

    acc = _wa_account(db_session, delegated=True, ai_enabled=True)
    _run(db_session, wa_payload(acc, "16315551234", "queued", "wamid.rb1"), "whatsapp_business_account")
    key = str(_conv(db_session, whatsapp_account_id=acc.id).id)
    user = type("U", (), {"id": uuid4()})()
    with patch("app.api.routes_saas_delegation._limit"), patch("app.api.routes_saas_delegation.write_audit_log"):
        _update(db_session, acc, user, SaasDelegationUpdate(saas_delegation_enabled=False), "whatsapp_account", "whatsapp")
    assert _deliver(db_session, key, saas).sent == 0 and saas.requests == []  # A13: never sent afterwards
    assert {e.status for e in _events(db_session, acc, "message.received")} == {"dropped"}
    after = _run(db_session, wa_payload(acc, "16315551234", "again", "wamid.rb2"), "whatsapp_business_account")
    assert after.wa_turn.delay.called  # Many's own AI path is back
    assert _deliver(db_session, key, saas).sent == 0 and saas.requests == []
