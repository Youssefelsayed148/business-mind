from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterator


MESSAGE_STATUSES = frozenset({"sent", "delivered", "read", "failed", "deleted"})
RAW_ONLY_FIELDS = frozenset({"message_template_quality_update", "account_update"})
_REFERRAL_FIELDS = (
    "source_url",
    "source_id",
    "source_type",
    "headline",
    "body",
    "media_type",
    "image_url",
    "video_url",
    "thumbnail_url",
)


@dataclass(frozen=True)
class ParsedWhatsappReferral:
    data: dict[str, str]


@dataclass(frozen=True)
class ParsedWhatsappMessageEvent:
    phone_number_id: str
    sender_wa_id: str
    text: str
    sender_profile_name: str | None
    message_id: str | None
    timestamp: str | None
    message_type: str
    referral: ParsedWhatsappReferral | None
    raw_event: dict


@dataclass(frozen=True)
class ParsedWhatsappStatusEvent:
    phone_number_id: str | None
    provider_message_id: str
    status: str
    timestamp: str | None
    recipient_wa_id: str | None
    conversation: dict | None
    pricing: dict | None
    errors: list[dict]
    raw_event: dict


@dataclass(frozen=True)
class ParsedWhatsappTemplateStatusEvent:
    whatsapp_business_account_id: str | None
    event: str
    message_template_id: str | None
    message_template_name: str | None
    message_template_language: str | None
    reason: str | None
    timestamp: str | None
    raw_event: dict


@dataclass(frozen=True)
class ParsedWhatsappPhoneQualityEvent:
    whatsapp_business_account_id: str | None
    display_phone_number: str
    event: str
    current_limit: str | None
    timestamp: str | None
    raw_event: dict


@dataclass(frozen=True)
class ParsedWhatsappRawOnlyEvent:
    field: str
    whatsapp_business_account_id: str | None
    timestamp: str | None
    raw_event: dict


def _changes(payload: dict) -> Iterator[tuple[str | None, str | None, str, dict]]:
    if not isinstance(payload, dict):
        return
    entries = payload.get("entry")
    if not isinstance(entries, list):
        return
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry_id = str(entry["id"]) if entry.get("id") is not None else None
        entry_time = str(entry["time"]) if entry.get("time") is not None else None
        changes = entry.get("changes")
        if not isinstance(changes, list):
            continue
        for change in changes:
            if not isinstance(change, dict) or not isinstance(change.get("value"), dict):
                continue
            field = change.get("field")
            if not isinstance(field, str):
                continue
            yield entry_id, entry_time, field, change["value"]


def _phone_number_id(value: dict) -> str | None:
    metadata = value.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("phone_number_id") is None:
        return None
    result = str(metadata["phone_number_id"])
    return result or None


def _profile_names(value: dict) -> dict[str, str]:
    result: dict[str, str] = {}
    contacts = value.get("contacts")
    if not isinstance(contacts, list):
        return result
    for contact in contacts:
        if not isinstance(contact, dict) or contact.get("wa_id") is None:
            continue
        profile = contact.get("profile")
        name = profile.get("name") if isinstance(profile, dict) else None
        if isinstance(name, str) and name:
            result[str(contact["wa_id"])] = name
    return result


def _message_text(message: dict) -> tuple[str, str] | None:
    message_type = message.get("type")
    if message_type == "text":
        text = message.get("text")
        body = text.get("body") if isinstance(text, dict) else None
        return (body, "text") if isinstance(body, str) and body else None
    if message_type == "button":
        button = message.get("button")
        if not isinstance(button, dict):
            return None
        value = button.get("payload") or button.get("text")
        return (str(value), "button") if value else None
    if message_type == "interactive":
        interactive = message.get("interactive")
        if not isinstance(interactive, dict):
            return None
        interactive_type = interactive.get("type")
        if interactive_type not in {"button_reply", "list_reply"}:
            return None
        reply = interactive.get(interactive_type)
        if not isinstance(reply, dict):
            return None
        value = reply.get("id") or reply.get("title")
        return (str(value), f"interactive_{interactive_type}") if value else None
    # The common message envelope (`from`, `id`, `timestamp`, `type`) is
    # sufficient to maintain identity and last-inbound state even when Phase
    # 1 has no content parser for the specific media/system message type.
    if isinstance(message_type, str) and message_type:
        return "", message_type
    return None


def _referral(message: dict) -> ParsedWhatsappReferral | None:
    referral = message.get("referral")
    if not isinstance(referral, dict):
        return None
    confirmed = {
        key: str(referral[key])
        for key in _REFERRAL_FIELDS
        if referral.get(key) is not None
    }
    return ParsedWhatsappReferral(confirmed) if confirmed else None


def parse_whatsapp_message_events(payload: dict) -> list[ParsedWhatsappMessageEvent]:
    events: list[ParsedWhatsappMessageEvent] = []
    for _, _, field, value in _changes(payload):
        if field != "messages":
            continue
        phone_number_id = _phone_number_id(value)
        if not phone_number_id:
            continue
        profiles = _profile_names(value)
        messages = value.get("messages")
        if not isinstance(messages, list):
            continue
        for message in messages:
            if not isinstance(message, dict) or message.get("from") is None:
                continue
            parsed_text = _message_text(message)
            if parsed_text is None:
                continue
            text, message_type = parsed_text
            sender_wa_id = str(message["from"])
            events.append(
                ParsedWhatsappMessageEvent(
                    phone_number_id=phone_number_id,
                    sender_wa_id=sender_wa_id,
                    text=text,
                    sender_profile_name=profiles.get(sender_wa_id),
                    message_id=str(message["id"]) if message.get("id") else None,
                    timestamp=(
                        str(message["timestamp"])
                        if message.get("timestamp") is not None
                        else None
                    ),
                    message_type=message_type,
                    referral=_referral(message),
                    raw_event=message,
                )
            )
    return events


def parse_whatsapp_unparsed_message_events(payload: dict) -> list[ParsedWhatsappMessageEvent]:
    """Customer messages `parse_whatsapp_message_events` drops because it has
    no content parser for them (a text with an empty body, a button or
    interactive message without a readable reply, a message with no type).
    Returned with empty text and message_type "unsupported" so a delegated
    channel can forward them (contract 4.1, A5). Only delegated code calls
    this; the regular parser and its handlers are untouched."""
    events: list[ParsedWhatsappMessageEvent] = []
    for _, _, field, value in _changes(payload):
        if field != "messages":
            continue
        phone_number_id = _phone_number_id(value)
        messages = value.get("messages")
        if not phone_number_id or not isinstance(messages, list):
            continue
        profiles = _profile_names(value)
        for message in messages:
            if not isinstance(message, dict) or message.get("from") is None:
                continue
            if _message_text(message) is not None:
                continue
            sender_wa_id = str(message["from"])
            events.append(
                ParsedWhatsappMessageEvent(
                    phone_number_id=phone_number_id,
                    sender_wa_id=sender_wa_id,
                    text="",
                    sender_profile_name=profiles.get(sender_wa_id),
                    message_id=str(message["id"]) if message.get("id") else None,
                    timestamp=(
                        str(message["timestamp"]) if message.get("timestamp") is not None else None
                    ),
                    message_type="unsupported",
                    referral=_referral(message),
                    raw_event=message,
                )
            )
    return events


def parse_whatsapp_status_events(payload: dict) -> list[ParsedWhatsappStatusEvent]:
    events: list[ParsedWhatsappStatusEvent] = []
    for _, _, field, value in _changes(payload):
        if field != "messages":
            continue
        statuses = value.get("statuses")
        if not isinstance(statuses, list):
            continue
        for status in statuses:
            if not isinstance(status, dict):
                continue
            provider_id = status.get("id")
            status_name = status.get("status")
            if not provider_id or status_name not in MESSAGE_STATUSES:
                continue
            errors = status.get("errors")
            events.append(
                ParsedWhatsappStatusEvent(
                    phone_number_id=_phone_number_id(value),
                    provider_message_id=str(provider_id),
                    status=str(status_name),
                    timestamp=(
                        str(status["timestamp"])
                        if status.get("timestamp") is not None
                        else None
                    ),
                    recipient_wa_id=(
                        str(status["recipient_id"])
                        if status.get("recipient_id") is not None
                        else None
                    ),
                    conversation=(
                        status["conversation"]
                        if isinstance(status.get("conversation"), dict)
                        else None
                    ),
                    pricing=(
                        status["pricing"]
                        if isinstance(status.get("pricing"), dict)
                        else None
                    ),
                    errors=[item for item in errors if isinstance(item, dict)]
                    if isinstance(errors, list)
                    else [],
                    raw_event=status,
                )
            )
    return events


def parse_whatsapp_template_status_events(
    payload: dict,
) -> list[ParsedWhatsappTemplateStatusEvent]:
    events: list[ParsedWhatsappTemplateStatusEvent] = []
    for entry_id, entry_time, field, value in _changes(payload):
        if field != "message_template_status_update" or not value.get("event"):
            continue
        template_id = value.get("message_template_id")
        template_name = value.get("message_template_name")
        if template_id is None and template_name is None:
            continue
        events.append(
            ParsedWhatsappTemplateStatusEvent(
                whatsapp_business_account_id=entry_id,
                event=str(value["event"]),
                message_template_id=(
                    str(template_id) if template_id is not None else None
                ),
                message_template_name=(
                    str(template_name) if template_name is not None else None
                ),
                message_template_language=(
                    str(value["message_template_language"])
                    if value.get("message_template_language") is not None
                    else None
                ),
                reason=(
                    str(value["reason"]) if value.get("reason") is not None else None
                ),
                timestamp=entry_time,
                raw_event=value,
            )
        )
    return events


def parse_whatsapp_phone_quality_events(
    payload: dict,
) -> list[ParsedWhatsappPhoneQualityEvent]:
    events: list[ParsedWhatsappPhoneQualityEvent] = []
    for entry_id, entry_time, field, value in _changes(payload):
        if field != "phone_number_quality_update":
            continue
        display_number = value.get("display_phone_number")
        event = value.get("event")
        if not display_number or not event:
            continue
        events.append(
            ParsedWhatsappPhoneQualityEvent(
                whatsapp_business_account_id=entry_id,
                display_phone_number=str(display_number),
                event=str(event),
                current_limit=(
                    str(value["current_limit"])
                    if value.get("current_limit") is not None
                    else None
                ),
                timestamp=entry_time,
                raw_event=value,
            )
        )
    return events


def parse_whatsapp_raw_only_events(payload: dict) -> list[ParsedWhatsappRawOnlyEvent]:
    return [
        ParsedWhatsappRawOnlyEvent(field, entry_id, entry_time, value)
        for entry_id, entry_time, field, value in _changes(payload)
        if field in RAW_ONLY_FIELDS
    ]


def whatsapp_status_event_key(event: ParsedWhatsappStatusEvent) -> str:
    return ":".join(
        (
            "whatsapp_status",
            event.provider_message_id,
            event.status,
            event.timestamp or "",
        )
    )


def whatsapp_template_status_event_key(
    event: ParsedWhatsappTemplateStatusEvent,
) -> str:
    entity = event.message_template_id or ":".join(
        (event.message_template_name or "", event.message_template_language or "")
    )
    return ":".join(
        ("whatsapp_template_status", entity, event.event, event.timestamp or "")
    )


def whatsapp_phone_quality_event_key(event: ParsedWhatsappPhoneQualityEvent) -> str:
    entity = hashlib.sha256(event.display_phone_number.encode("utf-8")).hexdigest()[:24]
    return ":".join(
        (
            "whatsapp_phone_quality",
            entity,
            event.event,
            event.current_limit or "",
            event.timestamp or "",
        )
    )
