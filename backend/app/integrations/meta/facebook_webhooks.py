import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ParsedFacebookCommentEvent:
    facebook_page_id: str
    post_id: str
    comment_id: str
    commenter_id: str
    commenter_name: str | None
    comment_text: str
    created_time: str | None
    raw_event: dict


@dataclass
class ParsedFacebookPostbackEvent:
    facebook_page_id: str
    sender_id: str
    payload: str
    mid: str | None
    timestamp: int | None
    raw_event: dict


@dataclass
class ParsedFacebookMessageEvent:
    """A plain-text inbound Messenger message to a Facebook Page.

    entry[].messaging[] is the same Messenger Platform event shape Instagram
    messaging uses (both ride on the same underlying infra) — this parser
    mirrors parse_instagram_message_events almost exactly.
    """

    facebook_page_id: str
    sender_id: str
    text: str
    mid: str | None
    timestamp: str | None
    raw_event: dict


def parse_facebook_comment_events(payload: dict) -> list[ParsedFacebookCommentEvent]:
    """Parse Facebook Page comment events from a Meta webhook payload
    (payload["object"] == "page").

    Structurally close to parse_instagram_comment_events, with two real
    differences confirmed against current Meta docs: the field name is
    "feed" (not IG's "mentions"/"comments"), and Facebook sends webhook
    notifications for comment edits and deletions too (value.verb can be
    "add" / "edited" / "remove") — Instagram's parser never had to defend
    against this. Only verb == "add" is treated as a new comment.
    """
    events: list[ParsedFacebookCommentEvent] = []
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

        page_id = str(entry.get("id", ""))

        for change in changes:
            if not isinstance(change, dict):
                continue

            field = change.get("field", "")
            value = change.get("value", {})
            if not isinstance(value, dict):
                continue

            if field != "feed" or value.get("item") != "comment":
                continue

            # Edits/deletes fire the same webhook field — only new comments
            # should ever trigger a keyword match + reply.
            if value.get("verb", "add") != "add":
                continue

            comment_id = str(value.get("comment_id", ""))
            if not comment_id:
                logger.warning("Missing comment_id in Facebook comment event")
                continue

            post_id = str(value.get("post_id", ""))
            if not post_id:
                logger.warning("Missing post_id in Facebook comment event", extra={"comment_id": comment_id})
                continue

            from_obj = value.get("from", {})
            commenter_id = str(from_obj.get("id", "")) if isinstance(from_obj, dict) else ""
            commenter_name = from_obj.get("name") if isinstance(from_obj, dict) else None

            events.append(
                ParsedFacebookCommentEvent(
                    facebook_page_id=page_id,
                    post_id=post_id,
                    comment_id=comment_id,
                    commenter_id=commenter_id,
                    commenter_name=commenter_name,
                    comment_text=str(value.get("message", "")),
                    created_time=value.get("created_time"),
                    raw_event=value,
                )
            )

    return events


def parse_facebook_postback_events(payload: dict) -> list[ParsedFacebookPostbackEvent]:
    """Mirrors parse_instagram_postback_events — same entry[].messaging[]
    Messenger Platform shape, shared infra between IG and FB. Kept as a
    separate function/file from the Instagram parser per this phase's hard
    constraint (no shared mutation of Instagram integration code), even
    though the shape is identical.
    """
    events: list[ParsedFacebookPostbackEvent] = []
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

        page_id = str(entry.get("id", ""))

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
                        continue
                    quick_reply = message.get("quick_reply")
                    if isinstance(quick_reply, dict) and quick_reply.get("payload"):
                        payload_str = str(quick_reply.get("payload"))
                        mid = message.get("mid")

            if not payload_str:
                continue

            events.append(
                ParsedFacebookPostbackEvent(
                    facebook_page_id=page_id,
                    sender_id=sender_id,
                    payload=payload_str,
                    mid=str(mid) if mid else None,
                    timestamp=item.get("timestamp"),
                    raw_event=item,
                )
            )

    return events


def parse_facebook_message_events(payload: dict) -> list[ParsedFacebookMessageEvent]:
    """Mirrors parse_instagram_message_events — same entry[].messaging[]
    shape and same exclusions (postback taps, echoes, quick-replies, non-text
    attachments handled elsewhere or ignored).
    """
    events: list[ParsedFacebookMessageEvent] = []
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

        page_id = str(entry.get("id", ""))

        for item in messaging:
            if not isinstance(item, dict):
                continue

            sender = item.get("sender", {})
            sender_id = str(sender.get("id", "")) if isinstance(sender, dict) else ""
            if not sender_id:
                continue

            if isinstance(item.get("postback"), dict) and item["postback"].get("payload"):
                continue

            message = item.get("message")
            if not isinstance(message, dict):
                continue
            if message.get("is_echo"):
                continue
            if isinstance(message.get("quick_reply"), dict) and message["quick_reply"].get("payload"):
                continue

            text = message.get("text")
            if not text or not isinstance(text, str):
                continue

            events.append(
                ParsedFacebookMessageEvent(
                    facebook_page_id=page_id,
                    sender_id=sender_id,
                    text=text,
                    mid=message.get("mid"),
                    timestamp=item.get("timestamp"),
                    raw_event=item,
                )
            )

    return events
