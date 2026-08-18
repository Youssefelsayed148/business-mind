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


@dataclass
class ParsedPostbackEvent:
    instagram_account_ig_user_id: str
    sender_ig_id: str
    payload: str
    mid: str | None
    timestamp: int | None
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


def parse_instagram_postback_events(payload: dict) -> list[ParsedPostbackEvent]:
    """Defensively parse Instagram messaging postback / quick-reply button-tap
    events from a Meta webhook payload.

    These arrive under entry[].messaging[] (distinct from entry[].changes[]
    used by comment events) and are only present once the app is subscribed
    to the "messaging_postbacks" and/or "messages" webhook fields.

    Handles both button shapes:
      - Generic Template "postback" buttons -> messaging[].postback.payload
      - Quick Reply buttons -> messaging[].message.quick_reply.payload

    Echoes of our own outbound messages (messaging[].message.is_echo) are
    skipped, since they are not user-initiated taps.
    """
    events: list[ParsedPostbackEvent] = []
    if not isinstance(payload, dict):
        return events
    entries = payload.get("entry", [])
    if not isinstance(entries, list):
        return events

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        messaging = entry.get("messaging", [])
        if not isinstance(messaging, list):
            continue

        ig_user_id = str(entry.get("id", ""))

        for item in messaging:
            if not isinstance(item, dict):
                continue

            sender = item.get("sender", {})
            sender_id = str(sender.get("id", "")) if isinstance(sender, dict) else ""
            if not sender_id:
                continue

            payload_str: str | None = None
            mid: str | None = None

            postback = item.get("postback")
            if isinstance(postback, dict) and postback.get("payload"):
                payload_str = str(postback.get("payload"))
                mid = postback.get("mid")

            if payload_str is None:
                message = item.get("message")
                if isinstance(message, dict):
                    if message.get("is_echo"):
                        # Our own outbound message reflected back — not a tap.
                        continue
                    quick_reply = message.get("quick_reply")
                    if isinstance(quick_reply, dict) and quick_reply.get("payload"):
                        payload_str = str(quick_reply.get("payload"))
                        mid = message.get("mid")

            if not payload_str:
                # Not a postback/quick-reply event (could be a plain text
                # message, read receipt, reaction, etc.) — ignore.
                continue

            events.append(
                ParsedPostbackEvent(
                    instagram_account_ig_user_id=ig_user_id,
                    sender_ig_id=sender_id,
                    payload=payload_str,
                    mid=str(mid) if mid else None,
                    timestamp=item.get("timestamp"),
                    raw_event=item,
                )
            )

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