"""Content-free account-erasure ledger; channel UUID deliberately has no FK."""
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AccountErasureJob(Base):
    __tablename__ = "account_erasure_jobs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "platform", "channel_id", name="uq_account_erasure_scope"),
        UniqueConstraint("request_id", name="uq_account_erasure_request"),
        CheckConstraint("platform IN ('instagram', 'facebook', 'whatsapp')", name="ck_account_erasure_platform"),
        CheckConstraint("state IN ('pending', 'waiting_remote_acceptance', 'local_erased', 'operator_action')", name="ck_account_erasure_state"),
        CheckConstraint("error_code IS NULL OR error_code IN ('missing_signing_configuration', 'unknown_remote_scope', 'remote_not_accepted', 'channel_missing', 'audit_scope_unproven')", name="ck_account_erasure_error"),
        CheckConstraint("identity_count >= 0 AND accepted_count >= 0 AND accepted_count <= identity_count", name="ck_account_erasure_counts"),
    )
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    channel_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, default=uuid.uuid4)
    receipt_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    state: Mapped[str] = mapped_column(String(30), nullable=False, server_default="pending")
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    event_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(PGUUID(as_uuid=True)), nullable=False, default=list)
    identity_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    accepted_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    local_erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    remote_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
