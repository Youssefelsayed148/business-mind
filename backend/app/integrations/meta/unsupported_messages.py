"""Delegated-mode parsing of customer messages the text parsers drop.

`parse_instagram_message_events` and `parse_facebook_message_events` return
only messages with text. A delegated channel must also forward voice, image,
sticker and other non-text customer messages as `unsupported` (contract 4.1,
A5), so the SaaS can store them and flag a human. These helpers are separate
from the existing parsers on purpose: those, and the handlers built on them,
stay exactly as they are; only delegated code calls these.
"""

from collections.abc import Iterator


def iter_unsupported_messaging_items(payload: dict) -> Iterator[tuple[str, str, dict, dict]]:
    """Yield (entry_id, sender_id, messaging_item, message) for genuine
    customer messages in an entry[].messaging[] payload that carry no text but
    do carry content Many cannot read (attachments, a sticker, or Meta's own
    `is_unsupported` flag).

    Skipped, as in the text parsers: echoes, postback taps, quick replies with
    a payload (Many-owned flows). Reactions and receipts have no `message`
    object and are never yielded; a message with neither text nor content
    (an unsent message) is not a customer message and is skipped.
    """
    if not isinstance(payload, dict):
        return
    entries = payload.get("entry", [])
    if not isinstance(entries, list):
        return
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        messaging = entry.get("messaging", [])
        if not isinstance(messaging, list):
            continue
        entry_id = str(entry.get("id", ""))
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
            if not isinstance(message, dict) or message.get("is_echo"):
                continue
            if isinstance(message.get("quick_reply"), dict) and message["quick_reply"].get("payload"):
                continue
            text = message.get("text")
            if text and isinstance(text, str):
                continue  # a text message: the regular parser owns it
            attachments = message.get("attachments")
            if (
                (isinstance(attachments, list) and attachments)
                or message.get("sticker_id")
                or message.get("is_unsupported")
            ):
                yield entry_id, sender_id, item, message


def parse_facebook_unsupported_message_events(payload: dict):
    from app.integrations.meta.facebook_webhooks import ParsedFacebookMessageEvent

    return [
        ParsedFacebookMessageEvent(
            facebook_page_id=page_id,
            sender_id=sender_id,
            text="",
            mid=message.get("mid"),
            timestamp=item.get("timestamp"),
            raw_event=item,
        )
        for page_id, sender_id, item, message in iter_unsupported_messaging_items(payload)
    ]


def parse_instagram_unsupported_message_events(payload: dict):
    from app.integrations.meta.webhooks import ParsedMessageEvent

    return [
        ParsedMessageEvent(
            instagram_account_ig_user_id=ig_user_id,
            sender_ig_id=sender_id,
            text="",
            mid=message.get("mid"),
            timestamp=item.get("timestamp"),
            raw_event=item,
        )
        for ig_user_id, sender_id, item, message in iter_unsupported_messaging_items(payload)
    ]
