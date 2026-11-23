from unittest.mock import MagicMock, patch

import pytest

from app.integrations.meta.webhooks import ParsedCommentEvent, parse_instagram_comment_events


SAMPLE_COMMENT_PAYLOAD = {
    "object": "instagram",
    "entry": [
        {
            "id": "17841400000000000",
            "time": 1234567890,
            "changes": [
                {
                    "field": "mentions",
                    "value": {
                        "item": "comment",
                        "media_id": "media_123",
                        "comment_id": "comment_456",
                        "from": {"id": "user_789", "username": "testuser"},
                        "message": "I want the prompt",
                    },
                }
            ],
        }
    ],
}


def test_parser_returns_comment_event():
    events = parse_instagram_comment_events(SAMPLE_COMMENT_PAYLOAD)
    assert len(events) == 1
    event = events[0]
    assert isinstance(event, ParsedCommentEvent)
    assert event.instagram_account_ig_user_id == "17841400000000000"
    assert event.media_id == "media_123"
    assert event.comment_id == "comment_456"
    assert event.commenter_ig_id == "user_789"
    assert event.username == "testuser"
    assert event.comment_text == "I want the prompt"


def test_non_comment_payload_returns_empty():
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": "123",
                "changes": [
                    {
                        "field": "mentions",
                        "value": {"item": "like", "media_id": "m1"},
                    }
                ],
            }
        ],
    }
    events = parse_instagram_comment_events(payload)
    assert events == []


def test_empty_payload_returns_empty():
    assert parse_instagram_comment_events({}) == []
    assert parse_instagram_comment_events(None) == []  # type: ignore[arg-type]


def test_parser_defensive_missing_fields():
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": "123",
                "changes": [
                    {
                        "field": "mentions",
                        "value": {
                            "item": "comment",
                            "comment_id": "c1",
                            "message": "hi",
                            # missing media_id
                        },
                    }
                ],
            }
        ],
    }
    events = parse_instagram_comment_events(payload)
    assert events == []
