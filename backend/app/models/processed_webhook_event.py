import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


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
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="meta")
    event_key: Mapped[str] = mapped_column(String(500), nullable=False)
    event_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
