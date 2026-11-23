from datetime import datetime, timedelta, timezone

from app.models.whatsapp_contact import WhatsappContact


def _now(value: datetime | None) -> datetime:
    return value or datetime.now(timezone.utc)


def in_service_window(contact: WhatsappContact, *, now: datetime | None = None) -> bool:
    return bool(
        contact.last_inbound_at
        and contact.last_inbound_at >= _now(now) - timedelta(hours=24)
    )


def in_free_entry_window(contact: WhatsappContact, *, now: datetime | None = None) -> bool:
    return bool(
        contact.free_entry_point_expires_at
        and contact.free_entry_point_expires_at >= _now(now)
    )
