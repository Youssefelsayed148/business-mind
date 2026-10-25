from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column


class SaasDelegationMixin:
    """Per-channel SaaS delegation settings (contract v1 + v1.1 delta).

    Shared by InstagramAccount, WhatsappAccount and FacebookPage. With
    saas_delegation_enabled false (the default) the channel behaves exactly
    as it did before these columns existed. Secrets are Fernet-encrypted via
    utils.crypto and are never returned by any API.
    """

    saas_delegation_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    saas_connection_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    saas_base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    saas_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    saas_previous_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    saas_previous_secret_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Written by the forwarder (M-02+); surfaced read-only in the dashboard.
    saas_last_forward_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    saas_last_forward_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    saas_degraded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Last channel.status pushed to the SaaS (M-05): transitions and the
    # 6-hourly heartbeat are decided against these.
    saas_last_health_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    saas_last_health_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
