"""Outgoing identity email (invitations, password reset). Console backend only for now.

The email provider is decision D4 and is still open, so the only backend is the
console one: it sends nothing. It keeps messages in a bounded in-memory outbox
(tests and local development read it) and never logs a body, because bodies carry
one-time links. Links are always built from ``settings.public_base_url``, never
from a request ``Host`` header (design 10, reset poisoning).
"""

import logging
from collections import deque
from dataclasses import dataclass
from typing import Protocol

from app.core.config import Settings

logger = logging.getLogger(__name__)

OUTBOX_LIMIT = 200


@dataclass(frozen=True)
class MailMessage:
    kind: str  # "invitation" or "password_reset"
    to: str
    subject: str
    body: str


class Mailer(Protocol):
    def send(self, message: MailMessage) -> None: ...


class ConsoleMailer:
    """Delivers nothing; remembers the last messages in process memory."""

    def __init__(self) -> None:
        self.outbox: deque[MailMessage] = deque(maxlen=OUTBOX_LIMIT)

    def send(self, message: MailMessage) -> None:
        self.outbox.append(message)
        # Kind only: no address, no subject, no body (the body holds a secret link).
        logger.info("identity mail queued on the console backend: kind=%s", message.kind)


_console = ConsoleMailer()


def get_mailer(settings: Settings) -> Mailer:
    if settings.mailer_backend == "console":
        return _console
    raise RuntimeError(f"Unknown mailer backend: {settings.mailer_backend!r}")


def console_outbox() -> deque[MailMessage]:
    return _console.outbox


def link(settings: Settings, path: str, token: str) -> str:
    """An absolute link on the configured public base URL (never the request Host)."""
    return f"{settings.public_base_url.rstrip('/')}{path}?token={token}"
