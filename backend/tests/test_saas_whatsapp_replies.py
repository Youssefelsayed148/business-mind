"""F-06: only genuine customer replies are forwarded from a delegated
WhatsApp channel (button/interactive replies, click-to-WhatsApp first
messages); Many-owned payloads and consent commands are not."""

from types import SimpleNamespace

import pytest

from app.models.whatsapp_contact import WhatsappContact
from app.services.saas_inbound import whatsapp_customer_text
from tests.conftest import skip_if_no_db
from tests.test_saas_delegation_dispatch import _env, _events, _wa_account, _run  # noqa: F401
from tests.test_whatsapp_message_dispatch import _dm_payload as wa_text_payload

SENDER = "16315551234"


def _button(button: dict):
    return {"type": "button", "button": button}


def _interactive(kind: str, reply: dict):
    return {"type": "interactive", "interactive": {"type": kind, kind: reply}}


def _payload(account, fields: dict, message_id="wamid.b"):
    payload = wa_text_payload(account, SENDER, "x", message_id)
    message = payload["entry"][0]["changes"][0]["value"]["messages"][0]
    message.pop("text")
    message.update(fields)
    return payload


def _event(message_type, raw):
    return SimpleNamespace(message_type=message_type, raw_event=raw, text="")


# --- text selection (pure) --------------------------------------------------


def test_button_reply_text_prefers_the_visible_label_over_the_payload():
    raw = _button({"text": "Book now", "payload": "btn_1"})
    assert whatsapp_customer_text(_event("button", raw)) == ("Book now", False)
    assert whatsapp_customer_text(_event("button", _button({"payload": "Only payload"}))) == ("Only payload", False)


@pytest.mark.parametrize("kind", ["button_reply", "list_reply"])
def test_interactive_reply_text_prefers_the_title_over_the_id(kind):
    raw = _interactive(kind, {"id": "opt_1", "title": "Option A"})
    assert whatsapp_customer_text(_event(f"interactive_{kind}", raw)) == ("Option A", False)
    assert whatsapp_customer_text(_event(f"interactive_{kind}", _interactive(kind, {"id": "opt_1"}))) == ("opt_1", False)


@pytest.mark.parametrize(
    "message_type, raw",
    [
        ("button", _button({"text": "Follow check", "payload": "FOLLOW_CHECK:abc"})),
        ("interactive_button_reply", _interactive("button_reply", {"id": "FOLLOW_CHECK:abc", "title": "Done"})),
        ("interactive_list_reply", _interactive("list_reply", {"id": "FOLLOW_CHECK:abc", "title": "Done"})),
    ],
)
def test_many_owned_payloads_are_recognised(message_type, raw):
    assert whatsapp_customer_text(_event(message_type, raw)) == ("", True)


def test_plain_text_and_media_use_the_event_text():
    assert whatsapp_customer_text(SimpleNamespace(message_type="text", raw_event={}, text="hello")) == ("hello", False)
    assert whatsapp_customer_text(SimpleNamespace(message_type="image", raw_event={}, text="")) == ("", False)


# --- webhook path -----------------------------------------------------------


@skip_if_no_db
@pytest.mark.parametrize(
    "fields, expected",
    [
        (_button({"text": "Yes please", "payload": "Yes please"}), "Yes please"),  # template quick reply
        (_button({"text": "Book now", "payload": "btn_1"}), "Book now"),
        (_interactive("button_reply", {"id": "opt_1", "title": "Option A"}), "Option A"),
        (_interactive("list_reply", {"id": "row_2", "title": "Row two"}), "Row two"),
    ],
)
def test_genuine_button_and_interactive_replies_are_forwarded_as_text(db_session, fields, expected):
    acc = _wa_account(db_session, delegated=True)
    result = _run(db_session, _payload(acc, fields), "whatsapp_business_account")
    assert not result.ai_touched
    [event] = _events(db_session, acc)
    assert event.payload["type"] == "text" and event.payload["text"] == expected


@skip_if_no_db
@pytest.mark.parametrize(
    "fields",
    [
        _button({"text": "Follow check", "payload": "FOLLOW_CHECK:abc"}),
        _interactive("button_reply", {"id": "FOLLOW_CHECK:abc", "title": "Done"}),
    ],
)
def test_many_owned_payloads_are_not_forwarded(db_session, fields):
    acc = _wa_account(db_session, delegated=True)
    result = _run(db_session, _payload(acc, fields), "whatsapp_business_account")
    assert _events(db_session, acc) == [] and not result.kick.called


@skip_if_no_db
@pytest.mark.parametrize(
    "fields",
    [
        _button({"text": "STOP", "payload": "STOP"}),
        _button({"text": "Unsubscribe", "payload": "unsubscribe"}),
        _interactive("button_reply", {"id": "stop", "title": "Stop messages"}),
        {"type": "text", "text": {"body": " Stop "}},
    ],
)
def test_consent_commands_are_not_forwarded_however_they_arrive(db_session, fields):
    acc = _wa_account(db_session, delegated=True)
    payload = _payload(acc, fields)
    result = _run(db_session, payload, "whatsapp_business_account")
    assert _events(db_session, acc) == [] and not result.kick.called
    contact = db_session.query(WhatsappContact).filter_by(whatsapp_account_id=acc.id).one()
    assert contact.marketing_consent == "opted_out"


REFERRAL = {"source_url": "https://example.test/ad", "source_id": "ad-1", "source_type": "ad"}


@skip_if_no_db
def test_click_to_whatsapp_first_message_is_forwarded_when_delegated(db_session):
    acc = _wa_account(db_session, delegated=True)
    payload = wa_text_payload(acc, SENDER, "hi, saw your ad", "wamid.ctwa", referral=REFERRAL)
    result = _run(db_session, payload, "whatsapp_business_account")
    assert not result.ai_touched
    [event] = _events(db_session, acc)
    assert event.payload["text"] == "hi, saw your ad" and event.payload["type"] == "text"
    # Many still records the free-entry-point window like any CTWA message.
    contact = db_session.query(WhatsappContact).filter_by(whatsapp_account_id=acc.id).one()
    assert contact.free_entry_point_expires_at is not None


@skip_if_no_db
def test_click_to_whatsapp_message_is_unchanged_when_not_delegated(db_session):
    acc = _wa_account(db_session, delegated=False, ai_enabled=True)
    payload = wa_text_payload(acc, SENDER, "hi, saw your ad", "wamid.ctwa2", referral=REFERRAL)
    result = _run(db_session, payload, "whatsapp_business_account")
    assert _events(db_session, acc) == []
    assert not result.wa_turn.delay.called and not result.generate.called  # consent branch still stops here
