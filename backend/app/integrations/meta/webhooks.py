import hashlib
import hmac
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ParsedCommentEvent:
    instagram_account_ig_user_id: str
    media_id: str
    comment_id: str
    commenter_ig_id: str
    username: str | None
    comment_text: str
    created_time: str | None
    raw_event: dict


def verify_meta_signature(raw_body: bytes, signature_header: str | None, app_secret: str) -> bool:
    if not signature_header:
        return False
    parts = signature_header.split("=")
    if len(parts) != 2 or parts[0] != "sha256":
        return False
    expected_signature = parts[1]
    computed_signature = hmac.new(
        app_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected_signature, computed_signature)


def parse_instagram_comment_events(payload: dict) -> list[ParsedCommentEvent]:
    """Defensively parse Instagram comment events from a Meta webhook payload.
    Returns an empty list if the payload is not a comment event or is malformed.
    """
    events: list[ParsedCommentEvent] = []
    if not isinstance(payload, dict):
        return events
    entries = payload.get("entry", [])
    if not isinstance(entries, list):
        return events
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        changes = entry.get("changes", [])
        if not isinstance(changes, list):
            continue
        for change in changes:
            if not isinstance(change, dict):
                continue

            # Real Meta webhook uses field="comments" at change level
            field = change.get("field", "")
            value = change.get("value", {})
            if not isinstance(value, dict):
                continue

            # Support both field="comments" and legacy item="comment" formats
            item_type = value.get("item", "")
            if field != "comments" and item_type != "comment":
                continue

            media_id = _extract_media_id(value)
            if not media_id:
                logger.warning("Missing media_id in comment event", extra={"value_keys": list(value.keys())})
                continue

            # Real payload: comment id is in "id" field, fallback to "comment_id"
            comment_id = str(value.get("id") or value.get("comment_id", ""))
            if not comment_id:
                logger.warning("Missing comment_id in comment event")
                continue

            commenter_id = str(value.get("from", {}).get("id", ""))
            if not commenter_id:
                commenter_id = str(value.get("sender_id", ""))

            # Real payload: comment text is in "text" field, fallback to "message"
            comment_text = str(value.get("text", "") or value.get("message", ""))
            username = value.get("from", {}).get("username") or value.get("sender_name")
            created_time = value.get("created_time")
            ig_user_id = str(entry.get("id", ""))

            events.append(
                ParsedCommentEvent(
                    instagram_account_ig_user_id=ig_user_id,
                    media_id=media_id,
                    comment_id=comment_id,
                    commenter_ig_id=commenter_id,
                    username=username,
                    comment_text=comment_text,
                    created_time=created_time,
                    raw_event=value,
                )
            )

    if not events and payload.get("object") == "instagram":
        logger.info("No comment events found in Instagram webhook", extra={"payload_summary": str(payload)[:500]})
    return events


def _extract_media_id(value: dict) -> str | None:
    media_id = value.get("media_id")
    if media_id:
        return str(media_id)
    # Real payload: media is nested under "media" key with "id"
    media = value.get("media", {})
    if isinstance(media, dict):
        mid = media.get("id", "")
        return str(mid) if mid else None
    return None