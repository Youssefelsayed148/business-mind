"""Console mailer: nothing leaves the process, bodies are never logged, links use the config."""

import logging

import pytest

from app.identity.mailer import ConsoleMailer, MailMessage, console_outbox, get_mailer, link
from tests.conftest import build_test_settings


def test_console_backend_is_the_default_and_keeps_a_bounded_outbox() -> None:
    settings = build_test_settings()
    assert settings.mailer_backend == "console"
    mailer = get_mailer(settings)
    before = len(console_outbox())
    mailer.send(MailMessage("invitation", "a@example.com", "Hi", "body"))
    assert len(console_outbox()) == before + 1
    local = ConsoleMailer()
    for i in range(500):
        local.send(MailMessage("invitation", f"u{i}@example.com", "s", "b"))
    assert len(local.outbox) == 200 and local.outbox[-1].to == "u499@example.com"


def test_unknown_backend_is_an_error() -> None:
    with pytest.raises(RuntimeError):
        get_mailer(build_test_settings(mailer_backend="smtp"))


def test_logs_carry_the_kind_only(caplog: pytest.LogCaptureFixture) -> None:
    secret = "tok-SECRET-1234567890"
    with caplog.at_level(logging.DEBUG):
        ConsoleMailer().send(
            MailMessage(
                "password_reset", "victim@example.com", "Reset", f"https://x/?token={secret}"
            )
        )
    text = caplog.text
    assert "password_reset" in text
    assert secret not in text and "victim@example.com" not in text and "Reset" not in text


def test_links_come_from_the_configured_base_url() -> None:
    settings = build_test_settings(public_base_url="https://app.example.com/")
    assert (
        link(settings, "/accept-invite", "abc") == "https://app.example.com/accept-invite?token=abc"
    )
