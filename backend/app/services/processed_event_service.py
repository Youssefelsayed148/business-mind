"""
Per-change webhook deduplication using the processed_webhook_events table.

build_event_key() produces a deterministic key for a single parsed comment
change.  check_and_mark_processed() inserts a row protected by the unique
constraint, returning True for new events and False for duplicates.
"""

import hashlib
import logging
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.processed_webhook_event import ProcessedWebhookEvent

logger = logging.getLogger(__name__)

_PROVIDER = "meta"

# Key namespace per platform. "ig" (not "instagram") for Instagram so existing
# keys are unchanged.
_KEY_PREFIXES = {
    "instagram": "ig",
    "facebook": "fb",
    "whatsapp": "wa",
}


def build_event_key(
    *,
    comment_id: str | None,
    entry_id: str | None = None,
    field: str | None = None,
    media_id: str | None = None,
    commenter_ig_id: str | None = None,
    comment_text: str | None = None,
    platform: str = "instagram",
) -> str:
    """Return a stable, deterministic key for one comment change.

    `platform` selects the key namespace, matching the per-platform prefixes
    the message paths already use ("whatsapp_message:", "facebook_message:").
    It defaults to "instagram" so every existing Instagram call site produces
    byte-identical keys to before -- important, because changing an Instagram
    key would make already-processed comments look new and re-deliver their
    DMs.
    """
    prefix = _KEY_PREFIXES.get(platform, platform)
    if comment_id:
        return f"{prefix}_comment:{comment_id}"

    # Fallback: hash the available fields so the key is still deterministic.
    raw = "|".join(
        v or ""
        for v in [entry_id, field, media_id, commenter_ig_id, comment_text]
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return f"{prefix}_fallback:{digest}"


def check_and_mark_processed(
    db: Session,
    event_key: str,
    event_type: str | None = None,
    metadata: dict | None = None,
) -> bool:
    """
    Attempt to record event_key as processed.

    Returns True  → event is new; caller should proceed with processing.
    Returns False → event is a duplicate; caller should skip.

    Race-safe: concurrent inserts for the same key will result in exactly one
    success (True) and all others returning False via IntegrityError.
    """
    record = ProcessedWebhookEvent(
        id=uuid.uuid4(),
        provider=_PROVIDER,
        event_key=event_key,
        event_type=event_type,
        metadata_=metadata,
    )
    try:
        db.add(record)
        db.flush()
        return True
    except IntegrityError:
        db.rollback()
        logger.debug(
            "Duplicate webhook change skipped",
            extra={"provider": _PROVIDER, "event_key": event_key},
        )
        return False
