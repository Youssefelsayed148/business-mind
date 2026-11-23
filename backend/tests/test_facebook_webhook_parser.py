from app.integrations.meta.facebook_webhooks import (
    ParsedFacebookCommentEvent,
    ParsedFacebookMessageEvent,
    parse_facebook_comment_events,
    parse_facebook_message_events,
)

SAMPLE_COMMENT_PAYLOAD = {
    "object": "page",
    "entry": [
        {
            "id": "page_123",
            "changes": [
                {
                    "field": "feed",
                    "value": {
                        "item": "comment",
                        "verb": "add",
                        "post_id": "page_123_post_456",
                        "comment_id": "comment_789",
                        "from": {"id": "user_111", "name": "Jane Doe"},
                        "message": "I want the promo",
                        "created_time": "2026-09-06T00:00:00+0000",
                    },
                }
            ],
        }
    ],
}


def test_parser_returns_comment_event():
    events = parse_facebook_comment_events(SAMPLE_COMMENT_PAYLOAD)
    assert len(events) == 1
    event = events[0]
    assert isinstance(event, ParsedFacebookCommentEvent)
    assert event.facebook_page_id == "page_123"
    assert event.post_id == "page_123_post_456"
    assert event.comment_id == "comment_789"
    assert event.commenter_id == "user_111"
    assert event.commenter_name == "Jane Doe"
    assert event.comment_text == "I want the promo"


def test_edited_comment_is_ignored():
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page_123",
                "changes": [
                    {
                        "field": "feed",
                        "value": {
                            "item": "comment",
                            "verb": "edited",
                            "post_id": "page_123_post_456",
                            "comment_id": "comment_789",
                            "from": {"id": "user_111"},
                            "message": "edited text",
                        },
                    }
                ],
            }
        ],
    }
    assert parse_facebook_comment_events(payload) == []


def test_removed_comment_is_ignored():
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page_123",
                "changes": [
                    {
                        "field": "feed",
                        "value": {
                            "item": "comment",
                            "verb": "remove",
                            "post_id": "page_123_post_456",
                            "comment_id": "comment_789",
                        },
                    }
                ],
            }
        ],
    }
    assert parse_facebook_comment_events(payload) == []


def test_non_comment_feed_item_ignored():
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page_123",
                "changes": [{"field": "feed", "value": {"item": "status", "post_id": "p1"}}],
            }
        ],
    }
    assert parse_facebook_comment_events(payload) == []


def test_empty_payload_returns_empty():
    assert parse_facebook_comment_events({}) == []
    assert parse_facebook_comment_events(None) == []  # type: ignore[arg-type]
    assert parse_facebook_message_events({}) == []


SAMPLE_MESSAGE_PAYLOAD = {
    "object": "page",
    "entry": [
        {
            "id": "page_123",
            "messaging": [
                {
                    "sender": {"id": "user_111"},
                    "recipient": {"id": "page_123"},
                    "timestamp": 1700000000,
                    "message": {"mid": "mid.1", "text": "hello there"},
                }
            ],
        }
    ],
}


def test_message_parser_returns_message_event():
    events = parse_facebook_message_events(SAMPLE_MESSAGE_PAYLOAD)
    assert len(events) == 1
    event = events[0]
    assert isinstance(event, ParsedFacebookMessageEvent)
    assert event.facebook_page_id == "page_123"
    assert event.sender_id == "user_111"
    assert event.text == "hello there"
    assert event.mid == "mid.1"


def test_message_echo_is_ignored():
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page_123",
                "messaging": [
                    {
                        "sender": {"id": "page_123"},
                        "message": {"mid": "mid.echo", "text": "our own message", "is_echo": True},
                    }
                ],
            }
        ],
    }
    assert parse_facebook_message_events(payload) == []


def test_postback_is_not_parsed_as_message():
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page_123",
                "messaging": [
                    {
                        "sender": {"id": "user_111"},
                        "postback": {"payload": "SOME_PAYLOAD", "mid": "mid.pb"},
                    }
                ],
            }
        ],
    }
    assert parse_facebook_message_events(payload) == []
