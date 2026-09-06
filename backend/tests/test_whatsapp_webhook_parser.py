from app.integrations.meta.whatsapp_webhooks import (
    ParsedWhatsappMessageEvent,
    parse_whatsapp_message_events,
)

SAMPLE_TEXT_MESSAGE_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [
        {
            "id": "waba_123",
            "changes": [
                {
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "display_phone_number": "16505551111",
                            "phone_number_id": "phone_456",
                        },
                        "contacts": [{"profile": {"name": "Jane Doe"}, "wa_id": "16315551234"}],
                        "messages": [
                            {
                                "from": "16315551234",
                                "id": "wamid.HBg",
                                "timestamp": "1700000000",
                                "text": {"body": "Hi, do you deliver?"},
                                "type": "text",
                            }
                        ],
                    },
                    "field": "messages",
                }
            ],
        }
    ],
}


def test_parser_returns_message_event():
    events = parse_whatsapp_message_events(SAMPLE_TEXT_MESSAGE_PAYLOAD)
    assert len(events) == 1
    event = events[0]
    assert isinstance(event, ParsedWhatsappMessageEvent)
    assert event.phone_number_id == "phone_456"
    assert event.sender_wa_id == "16315551234"
    assert event.text == "Hi, do you deliver?"
    assert event.sender_profile_name == "Jane Doe"
    assert event.message_id == "wamid.HBg"


def test_empty_payload_returns_empty():
    assert parse_whatsapp_message_events({}) == []
    assert parse_whatsapp_message_events(None) == []  # type: ignore[arg-type]


def test_non_text_message_ignored():
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba_123",
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "phone_456"},
                            "messages": [
                                {"from": "16315551234", "id": "wamid.1", "type": "image"}
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    assert parse_whatsapp_message_events(payload) == []


def test_status_callback_ignored():
    """value.statuses (delivery/read receipts) carries no `messages` key at all."""
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba_123",
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "phone_456"},
                            "statuses": [{"id": "wamid.1", "status": "delivered"}],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    assert parse_whatsapp_message_events(payload) == []


def test_missing_phone_number_id_skipped():
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba_123",
                "changes": [
                    {
                        "value": {
                            "metadata": {},
                            "messages": [
                                {"from": "16315551234", "id": "wamid.1", "type": "text", "text": {"body": "hi"}}
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    assert parse_whatsapp_message_events(payload) == []


def test_no_profile_name_still_parses_message():
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba_123",
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "phone_456"},
                            "messages": [
                                {"from": "16315551234", "id": "wamid.1", "type": "text", "text": {"body": "hi"}}
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    events = parse_whatsapp_message_events(payload)
    assert len(events) == 1
    assert events[0].sender_profile_name is None
