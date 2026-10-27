"""F-09: shared signing vectors and the payload rules the SaaS enforces.

No fake server: signatures are checked against the pinned vectors file and
payloads are produced by the real builders and checked against the SaaS
rules (version, id lengths, enums, caps, ISO timestamps)."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from app.models.message import Message
from app.models.saas_forward_event import SaasForwardEvent
from app.services.saas_health import sync_channel
from app.services.saas_inbound import build_message_received_payload, delegate_inbound
from app.services.saas_signing import compute_signature, sign_headers, verify_signature
from app.services.saas_status import emit_message_status
from tests.conftest import skip_if_no_db
from tests.test_saas_messages import CONN, _accept, _env, _world  # noqa: F401

VECTORS = json.loads((Path(__file__).parent / "fixtures" / "contract" / "signing_vectors.json").read_text("utf-8"))["vectors"]


# --- signing vectors --------------------------------------------------------


def test_vector_file_has_the_agreed_inputs():
    first, second = VECTORS
    assert first["secret"] == "s" * 40 and len(first["secret"]) == 40
    assert first["timestamp"] == "1760000000" and first["body_utf8"] == '{"text":"مرحبا ✓"}'
    assert first["signature"] == "sha256=5e40dcd701ffe2adc2ba2940bf94a02f3cbe639b1e7ec9a4ac59c4c146f13d50"
    assert second["body_utf8"] == "" and second["secret"] == first["secret"] and second["timestamp"] == first["timestamp"]


@pytest.mark.parametrize("vector", VECTORS, ids=[v["name"] for v in VECTORS])
def test_compute_signature_matches_the_shared_vectors(vector):
    body = vector["body_utf8"].encode("utf-8")
    assert compute_signature(vector["secret"], vector["timestamp"], body) == vector["signature"]
    headers = sign_headers("c", vector["secret"], body, now=int(vector["timestamp"]))
    assert headers["X-Osiris-Signature"] == vector["signature"]
    assert verify_signature(
        [vector["secret"]], vector["timestamp"], vector["signature"], body, now=int(vector["timestamp"])
    )
    assert not verify_signature(
        ["x" * 40], vector["timestamp"], vector["signature"], body, now=int(vector["timestamp"])
    )


def test_empty_body_vector_is_hmac_over_timestamp_and_dot():
    import hashlib
    import hmac

    vector = VECTORS[1]
    expected = hmac.new(vector["secret"].encode(), b"1760000000.", hashlib.sha256).hexdigest()
    assert vector["signature"] == "sha256=" + expected


# --- SaaS payload rules -----------------------------------------------------

CHANNELS = {"whatsapp", "messenger", "instagram"}
MANY_ERROR_CODES = {
    "window_closed", "template_required", "recipient_unreachable", "rate_limited",
    "channel_disconnected", "message_too_long", "unknown",
}
CHANNEL_STATUSES = {"connected", "token_expiring", "token_expired", "webhook_unhealthy", "disconnected"}


def _iso(value):
    assert isinstance(value, str) and value.endswith("Z"), value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def check_rules(payload: dict, configured_connection_id: str) -> None:
    assert payload["version"] == 1
    event_id = payload["event_id"]
    assert isinstance(event_id, str) and 1 <= len(event_id) <= 128
    assert payload["connection_id"] == configured_connection_id == configured_connection_id.lower()
    _iso(payload["occurred_at"])
    kind = payload["event_type"]
    if kind == "message.received":
        assert payload["channel"] in CHANNELS
        for key in ("external_contact_id", "external_conversation_id", "external_message_id"):
            assert isinstance(payload[key], str) and payload[key]
        assert payload["type"] in {"text", "unsupported"}
        if payload["type"] == "text":
            assert isinstance(payload["text"], str) and 0 < len(payload["text"]) <= 4000
        else:
            assert "text" not in payload
        contact = payload["contact"]
        assert isinstance(contact, dict) and set(contact) <= {"name", "phone", "handle"}
        assert all(isinstance(v, str) for v in contact.values())
        assert len(contact.get("name", "")) <= 200
        assert len(contact.get("phone", "")) <= 100
        assert len(contact.get("handle", "")) <= 200
        _iso(payload["received_at"])
        if "window_expires_at" in payload:
            _iso(payload["window_expires_at"])
        origin = payload.get("origin")
        if origin is not None:
            assert origin["type"] == "campaign"
            assert isinstance(origin["campaign_name"], str) and len(origin["campaign_name"]) <= 120
            assert isinstance(origin["opening_message_text"], str) and len(origin["opening_message_text"]) <= 2000
            assert isinstance(origin["campaign_ref"], str) and len(origin["campaign_ref"]) <= 128
    elif kind == "message.status":
        assert isinstance(payload["message_id"], str) and payload["message_id"]
        assert payload["status"] in {"sent", "delivered", "read", "failed"}
        if payload["status"] == "failed":
            assert payload["error_code"] in MANY_ERROR_CODES
            assert len(payload.get("error_detail", "")) <= 200
    elif kind == "channel.status":
        assert payload["status"] in CHANNEL_STATUSES
        assert len(payload.get("detail", "")) <= 200
        if "expires_at" in payload:
            _iso(payload["expires_at"])
    else:
        pytest.fail(f"unknown event type {kind}")


NOW = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
LOWER = CONN  # a lowercase UUID, the form apply_config stores


def _received(platform="whatsapp", **over):
    args = dict(
        platform=platform, connection_id=LOWER, event_id="in:x:1", external_contact_id="16315551234",
        contact={"name": "Sara", "phone": "+16315551234"}, conversation_id=uuid4(), external_message_id="wamid.1",
        message_type="text", text="hello", received_at=NOW, window_expires_at=NOW + timedelta(hours=24), origin=None,
    )
    args.update(over)
    return build_message_received_payload(**args)


@pytest.mark.parametrize("platform", ["whatsapp", "facebook", "instagram"])
def test_message_received_text_and_unsupported_satisfy_the_rules(platform):
    contact = {"handle": "sara_k"} if platform == "instagram" else {"name": "Sara"}
    text = _received(platform, contact=contact)
    unsupported = _received(platform, contact=contact, message_type="unsupported", text=None)
    check_rules(text, LOWER)
    check_rules(unsupported, LOWER)
    assert text["channel"] == {"facebook": "messenger"}.get(platform, platform)
    assert text["text"] == "hello" and "text" not in unsupported


def test_message_received_oversized_inputs_are_trimmed_to_the_caps():
    payload = _received(
        event_id="e" * 300,
        text="x" * 5000,
        contact={"name": "n" * 500, "phone": "9" * 500, "handle": "h" * 500, "extra": ""},
        origin={
            "type": "campaign", "campaign_name": "c" * 120, "opening_message_text": "o" * 2000,
            "campaign_ref": "r" * 128,
        },
    )
    check_rules(payload, LOWER)
    assert len(payload["text"]) == 4000 and len(payload["event_id"]) == 128
    assert len(payload["contact"]["name"]) == 200 and len(payload["contact"]["phone"]) == 100


def test_text_type_without_text_is_sent_as_unsupported():
    for empty in (None, ""):
        payload = _received(text=empty)
        check_rules(payload, LOWER)
        assert payload["type"] == "unsupported"


def test_message_received_with_no_contact_details_has_an_empty_contact_object():
    payload = _received(contact={"name": None, "phone": ""})
    assert payload["contact"] == {}
    check_rules(payload, LOWER)


@skip_if_no_db
def test_real_forwarded_events_satisfy_the_rules(db_session):
    w = _world(db_session, "whatsapp")
    channel = w.channel
    assert channel.saas_connection_id == LOWER

    # message.received through the real helper, with a campaign origin
    delegate_inbound(
        db_session, platform="whatsapp", channel=channel, lead=w.lead, external_contact_id=w.contact_id,
        contact={"name": "N" * 400, "phone": f"+{w.contact_id}"}, text="hi", message_type="text",
        external_message_id="wamid.rules", timestamp="1700000000", received_at=NOW, kick=False,
    )
    # message.status failed with an over-long detail
    accepted = _accept(db_session, w)
    message = db_session.get(Message, accepted.message_pk)
    assert emit_message_status(db_session, message, "failed", error_code="window_closed", error_detail="d" * 500, kick=False)
    assert emit_message_status(db_session, message, "sent", kick=False)
    # channel.status
    assert sync_channel(db_session, "whatsapp", channel, force=True, kick=False)

    events = db_session.query(SaasForwardEvent).filter_by(channel_id=channel.id).all()
    assert {e.event_type for e in events} == {"message.received", "message.status", "channel.status"}
    for event in events:
        check_rules(event.payload, LOWER)
        assert event.payload["connection_id"] == LOWER
