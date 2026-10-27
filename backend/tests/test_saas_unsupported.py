"""F-04: non-text customer messages are forwarded as `unsupported` on
delegated WhatsApp and Facebook channels; the existing parsers and every
non-delegated channel behave exactly as before."""

from unittest.mock import patch
from uuid import uuid4

import pytest

from app.integrations.meta.facebook_webhooks import parse_facebook_message_events
from app.integrations.meta.unsupported_messages import parse_facebook_unsupported_message_events
from app.integrations.meta.whatsapp_webhooks import (
    parse_whatsapp_message_events,
    parse_whatsapp_unparsed_message_events,
)
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.models.message import Message
from app.models.webhook_event import WebhookEvent
from tests.conftest import skip_if_no_db
from tests.test_facebook_message_dispatch import _dm_payload as fb_text_payload
from tests.test_saas_delegation_dispatch import (  # noqa: F401 (fixtures/helpers)
    _env,
    _events,
    _fb_page,
    _run,
    _wa_account,
)
from tests.test_whatsapp_message_dispatch import _dm_payload as wa_text_payload

SENDER = "16315551234"


# --- WhatsApp ---------------------------------------------------------------


def _wa_payload(account, message_overrides: dict, *, drop=("text",), message_id="wamid.x"):
    payload = wa_text_payload(account, SENDER, "x", message_id)
    message = payload["entry"][0]["changes"][0]["value"]["messages"][0]
    for key in drop:
        message.pop(key, None)
    message.update(message_overrides)
    return payload


# Messages the regular parser drops (no content parser for them).
UNPARSED = {
    "empty text body": ({"type": "text", "text": {"body": ""}}, ()),
    "button without text or payload": ({"type": "button", "button": {}}, ()),
    "interactive flow reply": ({"type": "interactive", "interactive": {"type": "nfm_reply", "nfm_reply": {}}}, ()),
    "interactive reply without id or title": (
        {"type": "interactive", "interactive": {"type": "button_reply", "button_reply": {}}}, ()),
    "no type": ({}, ("text", "type")),
}
# Messages the regular parser already returns with empty text.
MEDIA = ["image", "audio", "voice", "sticker", "video", "document", "location", "contacts", "unsupported"]


@pytest.mark.parametrize("case", list(UNPARSED))
def test_whatsapp_unparsed_parser_returns_only_what_the_regular_parser_drops(case):
    overrides, drop = UNPARSED[case]

    class Acc:
        phone_number_id = "pn1"

    payload = _wa_payload(Acc, overrides, drop=drop)
    assert parse_whatsapp_message_events(payload) == []
    [event] = parse_whatsapp_unparsed_message_events(payload)
    assert event.text == "" and event.message_type == "unsupported" and event.sender_wa_id == SENDER


def test_whatsapp_unparsed_parser_ignores_messages_the_regular_parser_keeps():
    class Acc:
        phone_number_id = "pn1"

    assert parse_whatsapp_unparsed_message_events(wa_text_payload(Acc, SENDER, "hello", "w1")) == []
    for message_type in MEDIA:
        payload = _wa_payload(Acc, {"type": message_type})
        assert len(parse_whatsapp_message_events(payload)) == 1
        assert parse_whatsapp_unparsed_message_events(payload) == []


@skip_if_no_db
@pytest.mark.parametrize("message_type", MEDIA)
def test_whatsapp_delegated_forwards_every_media_type_as_unsupported(db_session, message_type):
    acc = _wa_account(db_session, delegated=True)
    _run(db_session, _wa_payload(acc, {"type": message_type}, message_id="wamid.m"), "whatsapp_business_account")
    [event] = _events(db_session, acc)
    assert event.payload["type"] == "unsupported" and "text" not in event.payload
    assert event.payload["external_message_id"] == "wamid.m"


@skip_if_no_db
@pytest.mark.parametrize("case", list(UNPARSED))
def test_whatsapp_delegated_forwards_messages_the_parser_drops(db_session, case):
    overrides, drop = UNPARSED[case]
    acc = _wa_account(db_session, delegated=True, ai_enabled=False)
    result = _run(
        db_session, _wa_payload(acc, overrides, drop=drop, message_id="wamid.u"), "whatsapp_business_account"
    )
    assert not result.ai_touched
    [event] = _events(db_session, acc)
    assert event.payload["type"] == "unsupported" and "text" not in event.payload
    assert event.payload["external_contact_id"] == SENDER
    conv = db_session.query(Conversation).filter_by(whatsapp_account_id=acc.id).one()
    assert event.payload["external_conversation_id"] == str(conv.id)
    inbound = db_session.query(Message).filter_by(conversation_id=conv.id).one()
    assert inbound.direction == "inbound"


@skip_if_no_db
def test_whatsapp_unparsed_message_is_deduplicated(db_session):
    # A real duplicate insert rolls back the whole test transaction, so the
    # shared dedupe service is stubbed: "already processed" must forward nothing.
    from app.services.saas_inbound import delegated_whatsapp_unparsed_events, process_delegated_whatsapp_unparsed

    acc = _wa_account(db_session, delegated=True)
    payload = _wa_payload(acc, {"type": "interactive", "interactive": {"type": "nfm_reply"}}, message_id="wamid.d")
    events = delegated_whatsapp_unparsed_events(db_session, payload)
    with patch("app.services.whatsapp_webhook_service.check_and_mark_processed", return_value=False) as marked, patch(
        "app.services.saas_inbound._kick"
    ):
        process_delegated_whatsapp_unparsed(db_session, events)
    assert marked.call_args.kwargs["event_key"] == "whatsapp_message:wamid.d"
    assert _events(db_session, acc) == []


@skip_if_no_db
def test_whatsapp_non_delegated_account_ignores_unparsed_messages_as_before(db_session):
    acc = _wa_account(db_session, delegated=False)
    before = (db_session.query(Lead).count(), db_session.query(Message).count())
    result = _run(
        db_session,
        _wa_payload(acc, {"type": "interactive", "interactive": {"type": "nfm_reply"}}),
        "whatsapp_business_account",
    )
    assert (db_session.query(Lead).count(), db_session.query(Message).count()) == before
    assert _events(db_session, acc) == [] and not result.ai_touched and not result.kick.called
    last = db_session.query(WebhookEvent).order_by(WebhookEvent.created_at.desc()).first()
    assert last.processing_status == "skipped"  # same outcome as before this ticket


# --- Facebook / Messenger ---------------------------------------------------


def _messaging(page_id, message, *, sender="psid-1", **item_extra):
    item = {"sender": {"id": sender}, "recipient": {"id": page_id}, "timestamp": 1700000000, "message": message}
    item.update(item_extra)
    return {"object": "page", "entry": [{"id": page_id, "messaging": [item]}]}


IMAGE = {"mid": "m.img", "attachments": [{"type": "image", "payload": {"url": "https://cdn.example/x.jpg"}}]}


@pytest.mark.parametrize(
    "message",
    [
        IMAGE,
        {"mid": "m.aud", "attachments": [{"type": "audio", "payload": {"url": "u"}}]},
        {"mid": "m.stk", "sticker_id": 369239263222822},
        {"mid": "m.uns", "is_unsupported": True},
    ],
)
def test_facebook_unsupported_parser_picks_up_non_text_messages(message):
    payload = _messaging("pg1", message)
    assert parse_facebook_message_events(payload) == []  # the regular parser still drops them
    [event] = parse_facebook_unsupported_message_events(payload)
    assert event.text == "" and event.sender_id == "psid-1" and event.facebook_page_id == "pg1"
    assert event.mid == message["mid"]


@pytest.mark.parametrize(
    "payload",
    [
        _messaging("pg1", {**IMAGE, "is_echo": True}),
        _messaging("pg1", IMAGE, postback={"payload": "GET_STARTED"}),
        _messaging("pg1", {**IMAGE, "quick_reply": {"payload": "OWNED_BY_MANY"}}),
        _messaging("pg1", {"mid": "m.t", "text": "hello", "attachments": [{"type": "image"}]}),
        _messaging("pg1", {"mid": "m.empty"}),
        _messaging("pg1", {"mid": "m.none", "attachments": []}),
        {"object": "page", "entry": [{"id": "pg1", "messaging": [{"sender": {"id": "p"}, "reaction": {"emoji": "x"}}]}]},
        {"object": "page", "entry": [{"id": "pg1", "messaging": [{"sender": {"id": "p"}, "delivery": {"mids": ["m"]}}]}]},
        {"object": "page", "entry": "garbage"},
        "garbage",
    ],
)
def test_facebook_unsupported_parser_skips_everything_else(payload):
    assert parse_facebook_unsupported_message_events(payload) == []


@skip_if_no_db
def test_facebook_delegated_forwards_image_as_unsupported_without_ai(db_session):
    page = _fb_page(db_session, delegated=True, ai_enabled=False)
    page.status = "connected"
    db_session.commit()
    result = _run(db_session, _messaging(page.page_id, IMAGE), "page")
    assert not result.ai_touched
    [event] = _events(db_session, page)
    assert event.event_id == "in:facebook:m.img"
    assert event.payload["type"] == "unsupported" and "text" not in event.payload
    assert event.payload["channel"] == "messenger" and event.payload["external_contact_id"] == "psid-1"
    conv = db_session.query(Conversation).filter_by(facebook_page_id=page.id).one()
    assert event.payload["external_conversation_id"] == str(conv.id)
    result.kick.assert_called_once_with(str(conv.id))


@skip_if_no_db
def test_facebook_unsupported_message_is_deduplicated_and_text_still_forwarded(db_session):
    from app.integrations.meta.unsupported_messages import parse_facebook_unsupported_message_events
    from app.workers import tasks

    page = _fb_page(db_session, delegated=True)
    page.status = "connected"
    db_session.commit()
    events = parse_facebook_unsupported_message_events(_messaging(page.page_id, IMAGE))
    with patch.object(tasks, "check_and_mark_processed", return_value=False) as marked, patch(
        "app.services.saas_inbound._kick"
    ):
        tasks._process_delegated_facebook_unsupported(db_session, events)
    assert marked.call_args.kwargs["event_key"] == "facebook_message:psid-1:m.img"
    assert _events(db_session, page) == []

    _run(db_session, _messaging(page.page_id, IMAGE), "page")  # first delivery is forwarded
    _run(db_session, fb_text_payload(page.page_id, "psid-1", "and some text", "m.text"), "page")
    kinds = [(e.event_id, e.payload["type"]) for e in _events(db_session, page)]
    assert kinds == [("in:facebook:m.img", "unsupported"), ("in:facebook:m.text", "text")]


@skip_if_no_db
def test_facebook_non_delegated_page_ignores_non_text_messages_as_before(db_session):
    page = _fb_page(db_session, delegated=False)
    page.status = "connected"
    db_session.commit()
    before = (db_session.query(Lead).count(), db_session.query(Message).count(), db_session.query(Conversation).count())
    result = _run(db_session, _messaging(page.page_id, IMAGE), "page")
    assert (
        db_session.query(Lead).count(), db_session.query(Message).count(), db_session.query(Conversation).count()
    ) == before
    assert _events(db_session, page) == [] and not result.ai_touched and not result.kick.called
    last = db_session.query(WebhookEvent).order_by(WebhookEvent.created_at.desc()).first()
    assert last.processing_status == "skipped"


@skip_if_no_db
def test_facebook_delegated_but_disconnected_page_does_not_forward_unsupported(db_session):
    page = _fb_page(db_session, delegated=True)
    page.status = "disconnected"
    db_session.commit()
    _run(db_session, _messaging(page.page_id, IMAGE), "page")
    assert _events(db_session, page) == []
