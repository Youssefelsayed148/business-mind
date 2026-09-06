import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ParsedWhatsappMessageEvent:
    """A plain-text inbound WhatsApp message.

    WhatsApp Cloud API webhook shape (payload["object"] == "whatsapp_business_account"):
    entry[].changes[].value.metadata.phone_number_id identifies which of our
    numbers received the message; entry[].changes[].value.messages[] carries
    the inbound text, keyed by the sender's WA ID (their phone number,
    E.164 without the leading '+'). contacts[] carries the sender's profile
    name, matched by wa_id.
    """

    phone_number_id: str
    sender_wa_id: str
    text: str
    sender_profile_name: str | None
    message_id: str | None
    timestamp: str | None
    raw_event: dict


def parse_whatsapp_message_events(payload: dict) -> list[ParsedWhatsappMessageEvent]:
    """Parse plain-text inbound message events from a WhatsApp Cloud API
    webhook payload.

    Only handles `type == "text"` messages, mirroring
    parse_instagram_message_events' scope (no attachments/media yet — ignore
    rather than guess, consistent with that function's existing behavior).
    Status callbacks (delivered/read receipts, under
    `value.statuses`) are not messages and are ignored here.
    """
    events: list[ParsedWhatsappMessageEvent] = []
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
            value = change.get("value")
            if not isinstance(value, dict):
                continue

            metadata = value.get("metadata", {})
            phone_number_id = str(metadata.get("phone_number_id", "")) if isinstance(metadata, dict) else ""
            if not phone_number_id:
                continue

            contacts = value.get("contacts", [])
            profile_names: dict[str, str] = {}
            if isinstance(contacts, list):
                for contact in contacts:
                    if not isinstance(contact, dict):
                        continue
                    wa_id = contact.get("wa_id")
                    profile = contact.get("profile", {})
                    name = profile.get("name") if isinstance(profile, dict) else None
                    if wa_id and name:
                        profile_names[str(wa_id)] = name

            messages = value.get("messages", [])
            if not isinstance(messages, list):
                continue

            for message in messages:
                if not isinstance(message, dict):
                    continue
                if message.get("type") != "text":
                    # Media/location/interactive replies etc. — not handled
                    # by the AI layer yet; ignore rather than guess.
                    continue

                sender_wa_id = str(message.get("from", ""))
                if not sender_wa_id:
                    continue

                text_obj = message.get("text", {})
                body = text_obj.get("body") if isinstance(text_obj, dict) else None
                if not body or not isinstance(body, str):
                    continue

                events.append(
                    ParsedWhatsappMessageEvent(
                        phone_number_id=phone_number_id,
                        sender_wa_id=sender_wa_id,
                        text=body,
                        sender_profile_name=profile_names.get(sender_wa_id),
                        message_id=message.get("id"),
                        timestamp=message.get("timestamp"),
                        raw_event=message,
                    )
                )

    return events
