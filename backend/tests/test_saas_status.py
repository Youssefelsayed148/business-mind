"""M-04: message.status events - sent/failed from the send path for every
platform, delivered/read/failed from the WhatsApp status webhook, error
mapping on the wire, and delivery through the ordered/retried outbox."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
import pytest

from app.integrations.meta.messaging import MetaMessageResult
from app.integrations.meta.whatsapp_webhooks import ParsedWhatsappStatusEvent
from app.models.message import Message
from app.models.saas_forward_event import SaasForwardEvent
from app.services import saas_forwarder as fwd
from app.services import saas_outbound
from app.services.saas_status import emit_message_status
from app.services.whatsapp_webhook_service import process_whatsapp_status_events
from tests.conftest import skip_if_no_db
from tests.test_saas_messages import CONN, SECRET, _accept, _env, _world, clients  # noqa: F401


@pytest.fixture(autouse=True)
def _no_broker():
    with patch("app.services.saas_inbound._kick") as kick:
        yield kick


def _events(db, w, event_type="message.status"):
    db.expire_all()
    return (
        db.query(SaasForwardEvent)
        .filter_by(channel_id=w.channel.id, event_type=event_type)
        .order_by(SaasForwardEvent.seq)
        .all()
    )


def _fail(code, subcode=None):
    err = {"code": code, "message": "localised text"}
    if subcode is not None:
        err["error_subcode"] = subcode
    return MetaMessageResult(success=False, error_code="permission_error", error_message="x", raw_response={"error": err})


@skip_if_no_db
@pytest.mark.parametrize("platform", ["whatsapp", "facebook", "instagram"])
def test_successful_send_emits_sent_with_both_ids(db_session, clients, _no_broker, platform):  # noqa: F811
    w = _world(db_session, platform)
    acc = _accept(db_session, w)
    saas_message_id = db_session.query(saas_outbound.SaasOutboundMessage).filter_by(message_pk=acc.message_pk).one().message_id
    assert saas_outbound.deliver_message(db_session, acc.message_pk) == "sent"
    [event] = _events(db_session, w)
    p = event.payload
    assert event.event_id == f"st:{saas_message_id}:sent"
    assert event.ordering_key == str(w.conv.id)
    assert p["event_type"] == "message.status" and p["version"] == 1 and p["connection_id"] == CONN
    assert p["message_id"] == saas_message_id and p["status"] == "sent"
    assert p["external_message_id"] == "wamid.out"
    assert "error_code" not in p
    _no_broker.assert_called_with(str(w.conv.id))


@skip_if_no_db
@pytest.mark.parametrize(
    "platform,failure,expected",
    [
        ("whatsapp", _fail(131047), "window_closed"),
        ("whatsapp", _fail(131026), "recipient_unreachable"),
        ("whatsapp", _fail(131056), "rate_limited"),
        ("whatsapp", _fail(132001), "template_required"),
        ("whatsapp", _fail(190), "channel_disconnected"),
        ("facebook", _fail(10, 2534022), "window_closed"),
        ("facebook", _fail(100, 2018001), "recipient_unreachable"),
        ("instagram", _fail(4), "rate_limited"),
        ("instagram", _fail(190), "channel_disconnected"),
        ("instagram", _fail(999), "unknown"),
    ],
)
def test_meta_rejection_emits_failed_with_mapped_code(db_session, clients, platform, failure, expected):  # noqa: F811
    w = _world(db_session, platform)
    acc = _accept(db_session, w)
    for client in (clients.wa, clients.fb, clients.ig):
        client.send_text_message.return_value = failure
        client.send_direct_message.return_value = failure
    assert saas_outbound.deliver_message(db_session, acc.message_pk) == "failed"
    [event] = _events(db_session, w)
    p = event.payload
    assert p["status"] == "failed" and p["error_code"] == expected
    assert len(p["error_detail"]) <= 200 and "localised" not in p["error_detail"]
    assert "external_message_id" not in p


@skip_if_no_db
def test_timeout_is_failed_unknown_with_transport_detail(db_session, clients):  # noqa: F811
    w = _world(db_session)
    acc = _accept(db_session, w)
    clients.wa.send_text_message.return_value = MetaMessageResult(success=False, error_code="timeout", error_message="t")
    saas_outbound.deliver_message(db_session, acc.message_pk)
    [event] = _events(db_session, w)
    assert event.payload["error_code"] == "unknown" and event.payload["error_detail"] == "send failed: timeout"


@skip_if_no_db
@pytest.mark.parametrize(
    "mutate,expected",
    [
        (lambda w: setattr(w.channel, "status", "disconnected"), "channel_disconnected"),
    ],
)
def test_pre_send_failures_emit_failed(db_session, clients, mutate, expected):  # noqa: F811
    w = _world(db_session)
    acc = _accept(db_session, w)
    mutate(w)
    db_session.commit()
    saas_outbound.deliver_message(db_session, acc.message_pk)
    [event] = _events(db_session, w)
    assert event.payload["error_code"] == expected


@skip_if_no_db
def test_window_closed_and_too_long_emit_failed(db_session, clients):  # noqa: F811
    closed = _world(db_session, window_open=False)
    saas_outbound.deliver_message(db_session, _accept(db_session, closed).message_pk)
    assert _events(db_session, closed)[0].payload["error_code"] == "window_closed"
    long_ = _world(db_session)
    saas_outbound.deliver_message(db_session, _accept(db_session, long_, text="a" * 4097).message_pk)
    assert _events(db_session, long_)[0].payload["error_code"] == "message_too_long"


@skip_if_no_db
def test_skipped_duplicate_delivery_emits_nothing_extra(db_session, clients):  # noqa: F811
    w = _world(db_session)
    acc = _accept(db_session, w)
    saas_outbound.deliver_message(db_session, acc.message_pk)
    saas_outbound.deliver_message(db_session, acc.message_pk)
    assert len(_events(db_session, w)) == 1


@skip_if_no_db
def test_non_saas_messages_and_disabled_channels_emit_nothing(db_session, clients):  # noqa: F811
    w = _world(db_session)
    own = Message(lead_id=w.lead.id, conversation_id=w.conv.id, direction="outbound", content="own",
                  message_type="ai_conversation", status="sent")
    db_session.add(own)
    db_session.commit()
    assert emit_message_status(db_session, own, "sent") is False

    acc = _accept(db_session, w)
    w.channel.saas_delegation_enabled = False
    db_session.commit()
    saas_outbound.deliver_message(db_session, acc.message_pk)
    assert _events(db_session, w) == []


# --- WhatsApp status webhook -------------------------------------------------


def _wa_status(provider_id, status, *, ts="1700000100", errors=None):
    return ParsedWhatsappStatusEvent(
        phone_number_id="p1", provider_message_id=provider_id, status=status, timestamp=ts,
        recipient_wa_id="16315551234", conversation=None, pricing=None, errors=errors or [], raw_event={},
    )


def _sent_wa_message(db, clients, pid="wamid.out"):  # noqa: F811
    w = _world(db)
    acc = _accept(db, w)
    clients.wa.send_text_message.return_value = MetaMessageResult(success=True, provider_message_id=pid, raw_response={})
    saas_outbound.deliver_message(db, acc.message_pk)
    return w, acc


@skip_if_no_db
def test_whatsapp_delivered_and_read_are_forwarded_once_each_in_order(db_session, clients):  # noqa: F811
    w, _ = _sent_wa_message(db_session, clients)
    process_whatsapp_status_events(db_session, [_wa_status("wamid.out", "delivered"), _wa_status("wamid.out", "read", ts="1700000200")])
    events = _events(db_session, w)
    assert [e.payload["status"] for e in events] == ["sent", "delivered", "read"]
    assert events[1].payload["occurred_at"] == "2023-11-14T22:15:00Z"
    assert events[2].payload["occurred_at"] == "2023-11-14T22:16:40Z"


@skip_if_no_db
def test_whatsapp_status_going_backwards_is_not_forwarded(db_session, clients):  # noqa: F811
    w, _ = _sent_wa_message(db_session, clients)
    process_whatsapp_status_events(db_session, [_wa_status("wamid.out", "read", ts="1700000200")])
    process_whatsapp_status_events(db_session, [_wa_status("wamid.out", "delivered", ts="1700000300")])
    assert [e.payload["status"] for e in _events(db_session, w)] == ["sent", "read"]


@skip_if_no_db
def test_whatsapp_async_failure_maps_the_error_code(db_session, clients):  # noqa: F811
    w, _ = _sent_wa_message(db_session, clients)
    process_whatsapp_status_events(
        db_session, [_wa_status("wamid.out", "failed", errors=[{"code": 131026, "title": "Message undeliverable"}])]
    )
    failed = _events(db_session, w)[-1].payload
    assert failed["status"] == "failed" and failed["error_code"] == "recipient_unreachable"
    assert failed["error_detail"] == "meta code 131026"


@skip_if_no_db
def test_whatsapp_status_for_unrelated_message_emits_nothing(db_session, clients):  # noqa: F811
    w, _ = _sent_wa_message(db_session, clients)
    other = Message(lead_id=w.lead.id, conversation_id=w.conv.id, direction="outbound", content="own",
                    message_type="ai_conversation", status="sent", provider_message_id="wamid.own")
    db_session.add(other)
    db_session.commit()
    process_whatsapp_status_events(db_session, [_wa_status("wamid.own", "delivered")])
    assert [e.payload["status"] for e in _events(db_session, w)] == ["sent"]


# --- through the forwarder ---------------------------------------------------------


@skip_if_no_db
def test_status_events_are_delivered_signed_and_in_order_after_message_received(db_session, clients):  # noqa: F811
    from app.services.saas_inbound import delegate_inbound
    from app.services.saas_signing import verify_signature

    w = _world(db_session)
    delegate_inbound(
        db_session, platform="whatsapp", channel=w.channel, lead=w.lead, external_contact_id=w.contact_id,
        contact={}, text="hello", message_type="text", external_message_id="wamid.in", timestamp="1700000000",
        received_at=datetime.now(timezone.utc), kick=False,
    )
    acc = _accept(db_session, w)
    saas_outbound.deliver_message(db_session, acc.message_pk)

    seen = []

    def handler(request):
        assert verify_signature([SECRET], request.headers["x-osiris-timestamp"], request.headers["x-osiris-signature"], request.content)
        seen.append(json.loads(request.content))
        return httpx.Response(202, json={"status": "accepted"})

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    fwd.process_ordering_key(db_session, str(w.conv.id), client=client)
    assert [(p["event_type"], p.get("status")) for p in seen] == [("message.received", None), ("message.status", "sent")]
    assert seen[1]["message_id"].startswith("m-")


@skip_if_no_db
def test_failed_status_is_retried_with_the_same_event_id(db_session, clients):  # noqa: F811
    w = _world(db_session)
    acc = _accept(db_session, w, text="a" * 4097)
    saas_outbound.deliver_message(db_session, acc.message_pk)
    ids = []

    def handler(request):
        ids.append(json.loads(request.content)["event_id"])
        return httpx.Response(503 if len(ids) == 1 else 202)

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    first = fwd.process_ordering_key(db_session, str(w.conv.id), client=client)
    assert first.retry_in and first.sent == 0
    # past the backoff but well inside the 24 h budget
    later = datetime.now(timezone.utc) + timedelta(hours=1)
    second = fwd.process_ordering_key(db_session, str(w.conv.id), client=client, now=later)
    assert second.sent == 1 and ids[0] == ids[1]
