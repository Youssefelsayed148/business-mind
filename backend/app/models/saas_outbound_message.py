import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SaasOutboundMessage(Base):
    """A message the SaaS asked Many to send (POST /api/saas/messages).

    The unique (connection_id, message_id) pair is the idempotency record for
    the SaaS `message_id` (kept at least 7 days) and the link from the SaaS id
    to Many's own messages row, which `message.status` events refer back to.
    """

    __tablename__ = "saas_outbound_messages"
    __table_args__ = (
        UniqueConstraint("connection_id", "message_id", name="uq_saas_outbound_connection_message"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    connection_id: Mapped[str] = mapped_column(String(64), nullable=False)
    message_id: Mapped[str] = mapped_column(String(128), nullable=False)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    channel_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    message_pk: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("messages.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
