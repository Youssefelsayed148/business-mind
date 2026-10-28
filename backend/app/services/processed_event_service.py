"""
Per-change webhook deduplication using the processed_webhook_events table.

build_event_key() produces a deterministic key for a single parsed comment
change.  check_and_mark_processed() inserts a row protected by the unique
constraint, returning True for new events and False for duplicates.
"""

import hashlib
import logging
import re
import uuid

from sqlalchemy import null, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.processed_webhook_event import ProcessedWebhookEvent, SAFE_EVENT_TYPES

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


_HASH_PREFIX = "sha256:v1:"
_HASHED_KEY = re.compile(r"sha256:v1:[0-9a-f]{64}\Z")
_SAFE_EVENT_TYPES = frozenset(SAFE_EVENT_TYPES)


def storage_event_key(event_key: str) -> str:
    """Versioned opaque storage key; callers can keep their existing key builders.

    Already-normalized keys remain unchanged, including across migrations.
    The reserved prefix cannot be produced by any current raw key builder.
    """
    if _HASHED_KEY.fullmatch(event_key):
        return event_key
    return _HASH_PREFIX + hashlib.sha256(event_key.encode("utf-8")).hexdigest()


def check_and_mark_processed(
    db: Session,
    event_key: str,
    event_type: str | None = None,
    metadata: dict | None = None,
) -> bool:
    """Atomically claim a raw key without storing its identifiers/text.

    Legacy raw and normalized rows are treated as the same marker during the
    migration transition. Metadata is intentionally discarded; it is diagnostic
    only and previously contained customer IDs and message excerpts. No commit
    or caller rollback occurs here. Deploy migration0029 with old writers paused.
    """
    stored_key = storage_event_key(event_key)
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"processed:{_PROVIDER}:{stored_key}"},
    )
    rows = db.query(ProcessedWebhookEvent).filter(
        ProcessedWebhookEvent.provider == _PROVIDER,
        ProcessedWebhookEvent.event_key.in_({event_key, stored_key}),
    ).with_for_update().all()
    if rows:
        canonical = next((row for row in rows if row.event_key == stored_key), rows[0])
        oldest = min(row.received_at for row in rows)
        for row in rows:
            if row is not canonical:
                db.delete(row)
        db.flush()
        canonical.event_key = stored_key
        canonical.received_at = oldest
        canonical.metadata_ = null()
        if canonical.event_type not in _SAFE_EVENT_TYPES:
            canonical.event_type = None
        db.flush()
        logger.debug("Duplicate webhook change skipped", extra={"provider": _PROVIDER, "event_digest": stored_key})
        return False
    statement = pg_insert(ProcessedWebhookEvent).values(
        id=uuid.uuid4(), provider=_PROVIDER, event_key=stored_key,
        event_type=event_type if event_type in _SAFE_EVENT_TYPES else None,
        metadata=null(),
    ).on_conflict_do_nothing(index_elements=["provider", "event_key"]).returning(ProcessedWebhookEvent.id)
    return db.execute(statement).first() is not None
