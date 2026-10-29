import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


SAFE_EVENT_TYPES = (
    "ig_comment", "ig_message", "ig_postback", "facebook_comment", "facebook_message",
    "whatsapp_message", "whatsapp_message_status", "whatsapp_template_status", "whatsapp_phone_quality",
)
_SAFE_TYPE_CHECK = "event_type IS NULL OR event_type IN (" + ",".join(repr(value) for value in SAFE_EVENT_TYPES) + ")"


class ProcessedWebhookEvent(Base):
    """
    Per-change deduplication record for incoming webhook events.

    Each row represents one change (e.g. one Instagram comment) that has been
    received and accepted for processing. The (provider, event_key) unique
    constraint prevents duplicate processing even under concurrent delivery.

    Rows older than 30-90 days can be pruned safely — the live comment/message
    tables provide longer-term idempotency guarantees.
    """

    __tablename__ = "processed_webhook_events"
    __table_args__ = (
        UniqueConstraint("provider", "event_key", name="uq_processed_webhook_provider_key"),
        CheckConstraint("event_key ~ '^sha256:v1:[0-9a-f]{64}$'", name="ck_processed_event_key_hashed"),
        CheckConstraint("metadata IS NULL", name="ck_processed_event_metadata_empty"),
        CheckConstraint(_SAFE_TYPE_CHECK, name="ck_processed_event_type_safe"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="meta")
    # Opaque SHA-256 tombstone only; diagnostic metadata is intentionally empty.
    event_key: Mapped[str] = mapped_column(String(500), nullable=False)
    event_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
