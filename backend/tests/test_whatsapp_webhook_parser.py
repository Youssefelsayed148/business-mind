import pytest

from app.integrations.meta.whatsapp_webhooks import (
    parse_whatsapp_message_events,
    parse_whatsapp_phone_quality_events,
    parse_whatsapp_raw_only_events,
    parse_whatsapp_status_events,
    parse_whatsapp_template_status_events,
    whatsapp_phone_quality_event_key,
    whatsapp_status_event_key,
    whatsapp_template_status_event_key,
)


@pytest.fixture
def message_payload():
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "waba-1", "time": 1700000100, "extra": "ignored",
            "changes": [{"field": "messages", "value": {
                "metadata": {"phone_number_id": "phone-1", "display_phone_number": "+1"},
                "contacts": [{"wa_id": "16315551234", "profile": {"name": "Ada"}}],
                "messages": [
                    {"from": "16315551234", "id": "wamid.text", "timestamp": "1700000000", "type": "text", "text": {"body": "Hello"}, "unknown": True, "referral": {"source_url": "https://example.test/ad", "source_id": "ad-7", "source_type": "ad", "headline": "Offer", "body": "Body", "media_type": "image", "image_url": "https://example.test/a.jpg", "ctwa_clid": "not-stored"}},
                    {"from": "16315551234", "id": "wamid.button", "type": "button", "button": {"payload": "YES", "text": "Yes"}},
                    {"from": "16315551234", "id": "wamid.interactive", "type": "interactive", "interactive": {"type": "button_reply", "button_reply": {"id": "BUY", "title": "Buy"}}},
                    {"from": "16315551234", "id": "wamid.list", "type": "interactive", "interactive": {"type": "list_reply", "list_reply": {"title": "Plan A"}}},
                    {"from": "16315551234", "id": "wamid.image", "type": "image", "image": {"id": "media-1"}},
                ],
            }}],
        }],
    }


@pytest.fixture
def status_payload():
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "waba-1", "changes": [{"field": "messages", "value": {
            "metadata": {"phone_number_id": "phone-1"},
            "statuses": [
                {"id": "wamid.1", "status": "read", "timestamp": "300", "recipient_id": "16315551234", "conversation": {"id": "conv-1", "origin": {"type": "marketing"}}, "pricing": {"billable": True, "pricing_model": "CBP", "category": "marketing"}},
                {"id": "wamid.1", "status": "delivered", "timestamp": "200", "recipient_id": "16315551234"},
                {"id": "wamid.2", "status": "failed", "timestamp": "400", "errors": [{"code": 131048, "title": "Spam rate limit", "error_data": {"details": "Try later"}}]},
                {"id": "wamid.3", "status": "sent", "timestamp": "100"},
                {"id": "wamid.4", "status": "deleted", "timestamp": "500"},
                {"id": "wamid.5", "status": "unknown", "timestamp": "600"},
            ],
        }}]}],
    }


def test_parses_text_buttons_interactive_and_ctwa_referral(message_payload):
    events = parse_whatsapp_message_events(message_payload)
    assert [(event.message_type, event.text) for event in events] == [
        ("text", "Hello"), ("button", "YES"),
        ("interactive_button_reply", "BUY"), ("interactive_list_reply", "Plan A"),
        ("image", ""),
    ]
    assert events[0].sender_profile_name == "Ada"
    assert events[0].referral.data == {
        "source_url": "https://example.test/ad", "source_id": "ad-7",
        "source_type": "ad", "headline": "Offer", "body": "Body",
        "media_type": "image", "image_url": "https://example.test/a.jpg",
    }


def test_parses_all_confirmed_statuses_and_nested_keys(status_payload):
    events = parse_whatsapp_status_events(status_payload)
    assert [event.status for event in events] == ["read", "delivered", "failed", "sent", "deleted"]
    assert [event.timestamp for event in events[:2]] == ["300", "200"]
    assert events[0].conversation["origin"]["type"] == "marketing"
    assert events[0].pricing["category"] == "marketing"
    assert events[2].errors[0]["code"] == 131048
    assert whatsapp_status_event_key(events[0]) == "whatsapp_status:wamid.1:read:300"


def test_parses_template_phone_quality_and_raw_only_families():
    payload = {"object": "whatsapp_business_account", "entry": [{"id": "waba-1", "time": 1700000200, "changes": [
        {"field": "message_template_status_update", "value": {"event": "APPROVED", "message_template_id": "tpl-1", "message_template_name": "welcome", "message_template_language": "en_US", "reason": None, "extra": 1}},
        {"field": "phone_number_quality_update", "value": {"display_phone_number": "+1 (631) 555-1234", "event": "FLAGGED", "current_limit": "TIER_1K", "extra": 1}},
        {"field": "message_template_quality_update", "value": {"message_template_id": "tpl-1", "event": "FLAGGED"}},
        {"field": "account_update", "value": {"event": "DISABLED", "phone_number": "not-logged"}},
    ]}]}
    templates = parse_whatsapp_template_status_events(payload)
    qualities = parse_whatsapp_phone_quality_events(payload)
    raw_only = parse_whatsapp_raw_only_events(payload)
    assert templates[0].event == "APPROVED"
    assert templates[0].timestamp == "1700000200"
    assert qualities[0].display_phone_number == "+1 (631) 555-1234"
    assert qualities[0].current_limit == "TIER_1K"
    assert {event.field for event in raw_only} == {"message_template_quality_update", "account_update"}
    assert "tpl-1:APPROVED:1700000200" in whatsapp_template_status_event_key(templates[0])
    assert whatsapp_phone_quality_event_key(qualities[0]).endswith(":FLAGGED:TIER_1K:1700000200")


@pytest.mark.parametrize("payload", [{}, None, {"entry": [{}]}, {"entry": [{"changes": [{"field": "messages", "value": {}}]}]}])
def test_parsers_tolerate_missing_keys(payload):
    assert parse_whatsapp_message_events(payload) == []
    assert parse_whatsapp_status_events(payload) == []
    assert parse_whatsapp_template_status_events(payload) == []
    assert parse_whatsapp_phone_quality_events(payload) == []
    assert parse_whatsapp_raw_only_events(payload) == []
