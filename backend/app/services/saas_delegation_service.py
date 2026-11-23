"""Config helpers for per-channel SaaS delegation (M-01).

No forwarding or signing lives here; this module only validates and stores
the settings and renders them for the API without ever exposing a secret.
"""

import ipaddress
import socket
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from app.core.config import settings
from app.utils.crypto import decrypt_text, encrypt_text

SECRET_GRACE = timedelta(hours=24)
MIN_SECRET_LENGTH = 32
_BLOCKED_SUFFIXES = (".local", ".internal", ".localhost", ".lan", ".home.arpa")


class DelegationConfigError(ValueError):
    """Raised for an invalid delegation setting; the message is safe to show."""


def _is_production() -> bool:
    return settings.APP_ENV.lower() == "production"


def _is_blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_base_url(raw: str) -> str:
    """Return the normalised base URL (no trailing slash) or raise.

    In production the URL must be https and must not point at a private,
    loopback or link-local host (checked on literals and on every resolved
    address). Outside production http and local hosts are allowed so the
    fake SaaS server in the contract tests can run on localhost.
    """
    value = (raw or "").strip()
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise DelegationConfigError("Base URL must be an http(s) URL with a host.")
    if parts.username or parts.password:
        raise DelegationConfigError("Base URL must not contain credentials.")
    if parts.query or parts.fragment:
        raise DelegationConfigError("Base URL must not contain a query or fragment.")
    try:
        parts.port
    except ValueError:
        raise DelegationConfigError("Base URL has an invalid port.")

    if _is_production():
        if parts.scheme != "https":
            raise DelegationConfigError("Base URL must use https.")
        _reject_private_host(parts.hostname)

    return value.rstrip("/")


def _reject_private_host(host: str) -> None:
    lowered = host.lower().rstrip(".")
    if lowered == "localhost" or lowered.endswith(_BLOCKED_SUFFIXES):
        raise DelegationConfigError("Base URL must not point at a private or local host.")
    try:
        literal = ipaddress.ip_address(lowered.strip("[]"))
    except ValueError:
        literal = None
    if literal is not None:
        if _is_blocked_ip(literal):
            raise DelegationConfigError("Base URL must not point at a private or local host.")
        return
    try:
        infos = socket.getaddrinfo(lowered, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise DelegationConfigError("Base URL host could not be resolved.")
    for info in infos:
        if _is_blocked_ip(ipaddress.ip_address(info[4][0])):
            raise DelegationConfigError("Base URL must not point at a private or local host.")


def normalize_connection_id(raw: str | None) -> str | None:
    """Canonical lowercase UUID string, or None for an empty value.

    The SaaS compares the payload connection_id with its own lowercase UUID
    string, so any other spelling (uppercase, braces, no hyphens) would be a
    permanent 422 on every forwarded event.
    """
    value = (raw or "").strip()
    if not value:
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise DelegationConfigError("Connection id must be a UUID, for example 123e4567-e89b-12d3-a456-426614174000.")


def validate_secret(secret: str) -> str:
    if len(secret) < MIN_SECRET_LENGTH or secret != secret.strip():
        raise DelegationConfigError(
            f"Secret must be at least {MIN_SECRET_LENGTH} characters with no surrounding whitespace."
        )
    return secret


def set_secret(channel, secret: str, *, now: datetime | None = None) -> None:
    """Store a new current secret. An existing one becomes the previous
    secret, valid for the 24 h grace window (contract A12)."""
    now = now or datetime.now(timezone.utc)
    validate_secret(secret)
    if channel.saas_secret_encrypted:
        channel.saas_previous_secret_encrypted = channel.saas_secret_encrypted
        channel.saas_previous_secret_expires_at = now + SECRET_GRACE
    channel.saas_secret_encrypted = encrypt_text(secret)


def get_secrets(channel, *, now: datetime | None = None) -> tuple[str | None, str | None]:
    """(current, previous-if-unexpired) plaintext secrets, for the signer."""
    now = now or datetime.now(timezone.utc)
    current = decrypt_text(channel.saas_secret_encrypted) if channel.saas_secret_encrypted else None
    previous = None
    if (
        channel.saas_previous_secret_encrypted
        and channel.saas_previous_secret_expires_at
        and channel.saas_previous_secret_expires_at > now
    ):
        previous = decrypt_text(channel.saas_previous_secret_encrypted)
    return current, previous


def apply_config(channel, data: dict, *, now: datetime | None = None) -> None:
    """Apply a validated partial update. `data` holds only fields the caller
    sent. Enabling requires a connection id, base URL and secret."""
    if channel.status == "erasure_pending" and data.get("saas_delegation_enabled"):
        raise DelegationConfigError("Account erasure pending")
    now = now or datetime.now(timezone.utc)
    if "saas_connection_id" in data:
        channel.saas_connection_id = normalize_connection_id(data["saas_connection_id"])
    if "saas_base_url" in data:
        raw = data["saas_base_url"]
        channel.saas_base_url = validate_base_url(raw) if raw else None
    if data.get("secret"):
        set_secret(channel, data["secret"], now=now)
    if "saas_delegation_enabled" in data:
        enabled = bool(data["saas_delegation_enabled"])
        if enabled and not (
            channel.saas_connection_id and channel.saas_base_url and channel.saas_secret_encrypted
        ):
            raise DelegationConfigError(
                "Connection id, base URL and secret are required before enabling delegation."
            )
        if channel.saas_delegation_enabled and not enabled:
            channel.saas_degraded = False
        channel.saas_delegation_enabled = enabled


def config_response(
    channel, now: datetime | None = None, *, failed_events: int | None = None, retryable_failed_events: int | None = None
) -> dict:
    now = now or datetime.now(timezone.utc)
    previous_active = bool(
        channel.saas_previous_secret_encrypted
        and channel.saas_previous_secret_expires_at
        and channel.saas_previous_secret_expires_at > now
    )
    return {
        "saas_delegation_enabled": bool(channel.saas_delegation_enabled),
        "saas_connection_id": channel.saas_connection_id,
        "saas_base_url": channel.saas_base_url,
        "secret_set": bool(channel.saas_secret_encrypted),
        "previous_secret_active": previous_active,
        "previous_secret_expires_at": (
            channel.saas_previous_secret_expires_at.isoformat() if previous_active else None
        ),
        "last_forward_status": channel.saas_last_forward_status,
        "last_forward_at": (
            channel.saas_last_forward_at.isoformat() if channel.saas_last_forward_at else None
        ),
        # No forward queue exists until M-02; null means "not measured".
        "queue_depth": None,
        # Failed forwards (kept 30 days) and those an admin can still replay
        # (payload kept 7 days). null when the caller did not measure them.
        "failed_events": failed_events,
        "retryable_failed_events": retryable_failed_events,
        "degraded": bool(channel.saas_degraded),
    }


MANAGED_BY_SAAS_CODE = "CHANNEL_MANAGED_BY_SAAS"
MANAGED_BY_SAAS_MESSAGE = "Managed in the SaaS inbox"


def conversation_is_delegated(db: Session, conversation) -> bool:
    """True when the conversation's channel currently runs in delegated mode.
    Handoff, takeover and resume exist only in the SaaS for such a channel."""
    from app.models.facebook_page import FacebookPage
    from app.models.instagram_account import InstagramAccount
    from app.models.whatsapp_account import WhatsappAccount

    for model, fk in (
        (InstagramAccount, conversation.instagram_account_id),
        (WhatsappAccount, conversation.whatsapp_account_id),
        (FacebookPage, conversation.facebook_page_id),
    ):
        if fk is not None:
            channel = db.get(model, fk)
            if channel is not None and channel.saas_delegation_enabled:
                return True
    return False
