"""F-04 (Instagram part, awaiting owner confirmation): non-text Instagram DMs
are forwarded as `unsupported` only for delegated accounts; with delegation
off nothing changes."""

from unittest.mock import patch

import pytest

from app.integrations.meta.unsupported_messages import parse_instagram_unsupported_message_events
from app.integrations.meta.webhooks import parse_instagram_message_events
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.models.message import Message
from app.models.webhook_event import WebhookEvent
from tests.conftest import skip_if_no_db
from tests.test_cold_dm_ai_dispatch import _dm_payload as ig_text_payload
from tests.test_saas_delegation_dispatch import _env, _events, _ig_account, _run  # noqa: F401


def _payload(ig_user_id, message, *, sender="9000011", **item_extra):
    item = {"sender": {"id": sender}, "recipient": {"id": ig_user_id}, "timestamp": 1700000000000, "message": message}
    item.update(item_extra)
    return {"object": "instagram", "entry": [{"id": ig_user_id, "messaging": [item]}]}


IMAGE = {"mid": "mid.img", "attachments": [{"type": "image", "payload": {"url": "https://cdn.example/x.jpg"}}]}


@pytest.mark.parametrize(
    "message",
    [
        IMAGE,
        {"mid": "m.aud", "attachments": [{"type": "audio", "payload": {"url": "u"}}]},
        {"mid": "m.shr", "attachments": [{"type": "share", "payload": {}}]},
        {"mid": "m.uns", "is_unsupported": True},
    ],
)
def test_instagram_unsupported_parser_picks_up_non_text_messages(message):
    payload = _payload("ig1", message)
    assert parse_instagram_message_events(payload) == []  # the live parser is unchanged
    [event] = parse_instagram_unsupported_message_events(payload)
    assert event.text == "" and event.sender_ig_id == "9000011" and event.instagram_account_ig_user_id == "ig1"


@pytest.mark.parametrize(
    "payload",
    [
        _payload("ig1", {**IMAGE, "is_echo": True}),
        _payload("ig1", IMAGE, postback={"payload": "FOLLOW_CHECK:abc"}),
        _payload("ig1", {**IMAGE, "quick_reply": {"payload": "FOLLOW_CHECK:abc"}}),
        _payload("ig1", {"mid": "m.t", "text": "hi", "attachments": [{"type": "image"}]}),
        _payload("ig1", {"mid": "m.none"}),
    ],
)
def test_instagram_unsupported_parser_skips_echoes_follow_gate_taps_and_text(payload):
    assert parse_instagram_unsupported_message_events(payload) == []


@skip_if_no_db
def test_instagram_delegated_forwards_image_as_unsupported_without_ai(db_session):
    acc = _ig_account(db_session, delegated=True, ai_enabled=False, cold=False)
    result = _run(db_session, _payload(acc.ig_user_id, IMAGE), "instagram")
    assert not result.ai_touched
    [event] = _events(db_session, acc)
    assert event.event_id == "in:instagram:mid.img"
    assert event.payload["type"] == "unsupported" and "text" not in event.payload
    conv = db_session.query(Conversation).filter_by(instagram_account_id=acc.id).one()
    assert event.payload["external_conversation_id"] == str(conv.id)
    result.kick.assert_called_once_with(str(conv.id))


@skip_if_no_db
def test_instagram_unsupported_is_deduplicated_and_text_still_forwarded(db_session):
    from app.workers import tasks

    acc = _ig_account(db_session, delegated=True)
    events = parse_instagram_unsupported_message_events(_payload(acc.ig_user_id, IMAGE))
    with patch.object(tasks, "check_and_mark_processed", return_value=False) as marked, patch(
        "app.services.saas_inbound._kick"
    ):
        tasks._process_delegated_instagram_unsupported(db_session, events)
    assert marked.call_args.kwargs["event_key"] == "ig_message:9000011:mid.img"
    assert _events(db_session, acc) == []  # a re-delivery forwards nothing

    _run(db_session, _payload(acc.ig_user_id, IMAGE), "instagram")  # first delivery is forwarded
    _run(db_session, ig_text_payload(acc.ig_user_id, "9000011", "and text", "mid.text"), "instagram")
    kinds = [(e.event_id, e.payload["type"]) for e in _events(db_session, acc)]
    assert kinds == [("in:instagram:mid.img", "unsupported"), ("in:instagram:mid.text", "text")]


@skip_if_no_db
def test_instagram_non_delegated_account_ignores_non_text_messages_as_before(db_session):
    acc = _ig_account(db_session, delegated=False, ai_enabled=True, cold=True)
    before = (db_session.query(Lead).count(), db_session.query(Message).count(), db_session.query(Conversation).count())
    result = _run(db_session, _payload(acc.ig_user_id, IMAGE), "instagram")
    assert (
        db_session.query(Lead).count(), db_session.query(Message).count(), db_session.query(Conversation).count()
    ) == before
    assert _events(db_session, acc) == [] and not result.ai_touched and not result.kick.called
    last = db_session.query(WebhookEvent).order_by(WebhookEvent.created_at.desc()).first()
    assert last.processing_status == "skipped"


@skip_if_no_db
def test_instagram_delegated_but_disconnected_account_does_not_forward_unsupported(db_session):
    acc = _ig_account(db_session, delegated=True, status="disconnected")
    _run(db_session, _payload(acc.ig_user_id, IMAGE), "instagram")
    assert _events(db_session, acc) == []
