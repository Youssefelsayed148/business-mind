"""F-07: a delegated send is retried (max 3 times, with backoff) only when
Meta definitely refused it with a rate-limit error; a timeout or an unknown
outcome is never retried. Error-code table checks."""

from unittest.mock import patch

import pytest

from app.integrations.meta.messaging import MetaMessageResult
from app.models.message import Message
from app.services import saas_error_mapping as mapping
from app.services import saas_outbound
from tests.conftest import skip_if_no_db
from tests.test_saas_messages import _accept, _env, _ok, _world, clients  # noqa: F401


def _meta_error(code, subcode=None, *, transport=None):
    if transport:
        return MetaMessageResult(success=False, error_code=transport, error_message="x", raw_response={})
    return MetaMessageResult(
        success=False, error_code="permission_error", error_message="localised text",
        raw_response={"error": {"code": code, "error_subcode": subcode, "message": "localised text"}},
    )


# --- mapping table ----------------------------------------------------------


@pytest.mark.parametrize(
    "platform, code, subcode, expected",
    [
        ("whatsapp", 131047, None, "window_closed"),
        ("whatsapp", 131026, None, "recipient_unreachable"),
        ("whatsapp", 130429, None, "rate_limited"),
        ("whatsapp", 131056, None, "rate_limited"),
        ("whatsapp", 131058, None, "template_required"),
        ("whatsapp", 132000, None, "template_required"),
        ("whatsapp", 132015, None, "template_required"),
        ("whatsapp", 190, None, "channel_disconnected"),
        ("facebook", 10, 2534022, "window_closed"),
        ("instagram", 10, 2018278, "window_closed"),
        ("facebook", 100, 2018001, "recipient_unreachable"),
        ("facebook", 4, None, "rate_limited"),
        ("instagram", 17, None, "rate_limited"),
        ("facebook", 32, None, "rate_limited"),
        ("instagram", 613, None, "rate_limited"),
        ("facebook", 190, None, "channel_disconnected"),
        ("instagram", 102, None, "channel_disconnected"),
        ("facebook", 999, None, "unknown"),
        ("whatsapp", None, None, "unknown"),
    ],
)
def test_error_table(platform, code, subcode, expected):
    assert mapping.map_meta_error(platform, code, subcode) == expected


@pytest.mark.parametrize("platform", ["whatsapp", "facebook", "instagram"])
def test_code_551_is_not_mapped_until_the_owner_verifies_it(platform):
    # Only third-party docs list 551 / subcode 1545041; see the module docstring.
    assert mapping.map_meta_error(platform, 551, 1545041) == "unknown"
    assert mapping.map_meta_error(platform, 551) == "unknown"


def test_every_row_documents_its_verification_status():
    source = open(mapping.__file__, encoding="utf-8").read()
    assert source.count("# unverified") + source.count("# verified") >= 12
    assert "551" in source and "NOT mapped" in source


# --- definite rate limit detection -----------------------------------------


@pytest.mark.parametrize(
    "platform, result, expected",
    [
        ("whatsapp", _meta_error(130429), True),
        ("facebook", _meta_error(613), True),
        ("instagram", _meta_error(4), True),
        ("whatsapp", _meta_error(131047), False),
        ("whatsapp", _meta_error(None), False),
        ("whatsapp", _meta_error(130429, transport="timeout"), False),
        ("whatsapp", MetaMessageResult(success=False, error_code="timeout", error_message="x", raw_response={"error": {"code": 130429}}), False),
        ("facebook", _meta_error(613, transport="network_error"), False),
        ("facebook", _meta_error(613, transport="invalid_json"), False),
        ("whatsapp", _ok(), False),
        ("whatsapp", None, False),
    ],
)
def test_definite_rate_limit(platform, result, expected):
    assert saas_outbound.definite_rate_limit(platform, result) is expected


# --- delivery ---------------------------------------------------------------


@pytest.fixture
def sleeps():
    with patch.object(saas_outbound.time, "sleep") as sleep:
        yield sleep


def _send_mock(clients, platform):
    return {"whatsapp": clients.wa.send_text_message}.get(platform) or getattr(
        clients, "fb" if platform == "facebook" else "ig"
    ).send_direct_message


@skip_if_no_db
@pytest.mark.parametrize(
    "platform, code", [("whatsapp", 130429), ("facebook", 613), ("instagram", 4)]
)
def test_rate_limit_is_retried_then_succeeds(db_session, clients, sleeps, platform, code):
    w = _world(db_session, platform)
    acc = _accept(db_session, w)
    send = _send_mock(clients, platform)
    send.side_effect = [_meta_error(code), _meta_error(code), _ok()]
    assert saas_outbound.deliver_message(db_session, acc.message_pk) == "sent"
    assert send.call_count == 3
    assert [round(c.args[0]) for c in sleeps.call_args_list] in ([2, 5], [3, 7], [2, 6], [3, 6], [2, 7], [3, 5])
    assert db_session.get(Message, acc.message_pk).status == "sent"


@skip_if_no_db
def test_persistent_rate_limit_gives_up_after_three_retries_and_reports_failed(db_session, clients, sleeps):
    w = _world(db_session, "whatsapp")
    acc = _accept(db_session, w)
    clients.wa.send_text_message.return_value = _meta_error(130429)
    assert saas_outbound.deliver_message(db_session, acc.message_pk) == "failed"
    assert clients.wa.send_text_message.call_count == 4  # first attempt + 3 retries
    assert sleeps.call_count == 3
    delays = [c.args[0] for c in sleeps.call_args_list]
    assert delays[0] < delays[1] < delays[2]
    message = db_session.get(Message, acc.message_pk)
    assert message.status == "failed" and message.error_code == "rate_limited"


@skip_if_no_db
@pytest.mark.parametrize("transport", ["timeout", "network_error", "invalid_json"])
def test_unknown_outcomes_are_never_retried(db_session, clients, sleeps, transport):
    w = _world(db_session, "whatsapp")
    acc = _accept(db_session, w)
    clients.wa.send_text_message.return_value = _meta_error(None, transport=transport)
    assert saas_outbound.deliver_message(db_session, acc.message_pk) == "failed"
    assert clients.wa.send_text_message.call_count == 1 and not sleeps.called


@skip_if_no_db
@pytest.mark.parametrize("code, expected", [(131047, "window_closed"), (131026, "recipient_unreachable"), (551, "unknown")])
def test_other_meta_errors_are_not_retried(db_session, clients, sleeps, code, expected):
    w = _world(db_session, "whatsapp")
    acc = _accept(db_session, w)
    clients.wa.send_text_message.return_value = _meta_error(code)
    assert saas_outbound.deliver_message(db_session, acc.message_pk) == "failed"
    assert clients.wa.send_text_message.call_count == 1 and not sleeps.called
    assert db_session.get(Message, acc.message_pk).error_code == expected


@skip_if_no_db
def test_a_successful_first_send_never_sleeps(db_session, clients, sleeps):
    w = _world(db_session, "whatsapp")
    assert saas_outbound.deliver_message(db_session, _accept(db_session, w).message_pk) == "sent"
    assert not sleeps.called
