"""M-02: outbox delivery - signing on the wire, retry/backoff, ordering,
budget, dropping on disable (contract section 6, delta A7/A13)."""

import json
import random
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.core.config import settings
from app.models.saas_forward_event import SaasForwardEvent
from app.models.whatsapp_account import WhatsappAccount
from app.models.workspace import Workspace
from app.services import saas_forwarder as fwd
from app.services import saas_delegation_service as delegation
from app.services.saas_signing import verify_signature
from tests.conftest import skip_if_no_db

SECRET = "k" * 40
T0 = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    from cryptography.fernet import Fernet

    from app.utils import crypto

    monkeypatch.setattr(settings, "TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(crypto, "_fernet", None)
    monkeypatch.setattr(settings, "APP_ENV", "test")
    yield
    monkeypatch.setattr(crypto, "_fernet", None)


class FakeSaas:
    """Records requests and replays configured responses."""

    def __init__(self, *responses):
        self.requests: list[httpx.Request] = []
        self.responses = list(responses)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        return item

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler), follow_redirects=False)


def _resp(code, headers=None):
    return httpx.Response(code, headers=headers or {}, json={"status": "accepted"})


@pytest.fixture
def account(db_session):
    ws = Workspace(id=uuid4(), name="W", slug=f"w-{uuid4()}")
    db_session.add(ws)
    db_session.flush()
    acc = WhatsappAccount(id=uuid4(), workspace_id=ws.id, phone_number_id=f"p{uuid4().hex}")
    delegation.apply_config(
        acc,
        {
            "saas_connection_id": "11111111-1111-4111-8111-111111111111",
            "saas_base_url": "https://saas.example.com",
            "secret": SECRET,
            "saas_delegation_enabled": True,
        },
    )
    db_session.add(acc)
    db_session.commit()
    return acc


def _enqueue(db, acc, event_id, key="conv-1", text="hi"):
    assert fwd.enqueue_event(
        db,
        platform="whatsapp",
        channel=acc,
        ordering_key=key,
        event_id=event_id,
        event_type="message.received",
        payload={"event_id": event_id, "event_type": "message.received", "text": text},
        now=T0,
    )
    db.commit()


def _row(db, event_id):
    db.expire_all()
    return db.query(SaasForwardEvent).filter_by(event_id=event_id).one()


@skip_if_no_db
def test_success_is_signed_to_the_contract_url_and_clears_payload(db_session, account):
    _enqueue(db_session, account, "e1", text="héllo")
    saas = FakeSaas(_resp(202))
    result = fwd.process_ordering_key(db_session, "conv-1", client=saas.client(), now=T0)
    assert result.sent == 1
    request = saas.requests[0]
    assert str(request.url) == "https://saas.example.com/api/channels/manyosiris/events"
    assert request.headers["x-osiris-connection"] == "11111111-1111-4111-8111-111111111111"
    assert verify_signature(
        [SECRET], request.headers["x-osiris-timestamp"], request.headers["x-osiris-signature"], request.content
    )
    assert json.loads(request.content)["event_id"] == "e1"
    row = _row(db_session, "e1")
    assert row.status == "sent" and row.payload == {}
    db_session.refresh(account)
    assert account.saas_last_forward_status == "sent_202" and account.saas_degraded is False


@skip_if_no_db
@pytest.mark.parametrize("failure", [_resp(500), _resp(503), _resp(429), httpx.ConnectError("boom"), httpx.ReadTimeout("slow")])
def test_retryable_failures_back_off_keep_event_id_and_mark_degraded(db_session, account, failure):
    _enqueue(db_session, account, "e1")
    saas = FakeSaas(failure)
    result = fwd.process_ordering_key(db_session, "conv-1", client=saas.client(), now=T0, rng=random.Random(1))
    assert result.sent == 0 and result.retry_in and result.retry_in > 0
    row = _row(db_session, "e1")
    assert row.status == "pending" and row.attempts == 1 and row.next_attempt_at > T0
    db_session.refresh(account)
    assert account.saas_degraded is True and account.saas_last_forward_status == "retrying"

    # Not due yet: no request is made.
    again = FakeSaas(_resp(202))
    fwd.process_ordering_key(db_session, "conv-1", client=again.client(), now=T0 + timedelta(seconds=1))
    assert again.requests == []

    # Due: same event_id goes out and succeeds, degraded clears.
    later = row.next_attempt_at + timedelta(seconds=1)
    fwd.process_ordering_key(db_session, "conv-1", client=again.client(), now=later)
    assert json.loads(again.requests[0].content)["event_id"] == "e1"
    assert _row(db_session, "e1").status == "sent"
    db_session.refresh(account)
    assert account.saas_degraded is False


@skip_if_no_db
def test_retry_after_is_honoured_on_429(db_session, account):
    _enqueue(db_session, account, "e1")
    fwd.process_ordering_key(
        db_session, "conv-1", client=FakeSaas(_resp(429, {"Retry-After": "600"})).client(), now=T0
    )
    assert _row(db_session, "e1").next_attempt_at >= T0 + timedelta(seconds=600)


@skip_if_no_db
@pytest.mark.parametrize("code", [400, 403, 404, 422])
def test_other_4xx_are_permanent_and_not_retried(db_session, account, code):
    _enqueue(db_session, account, "e1")
    saas = FakeSaas(_resp(code))
    result = fwd.process_ordering_key(db_session, "conv-1", client=saas.client(), now=T0)
    assert result.failed == 1 and len(saas.requests) == 1
    assert _row(db_session, "e1").status == "failed"
    db_session.refresh(account)
    assert account.saas_last_forward_status == f"rejected_{code}"


@skip_if_no_db
def test_401_is_retried_with_backoff_marks_auth_rejected_and_keeps_payload(db_session, account):
    _enqueue(db_session, account, "e1", text="keep")
    saas = FakeSaas(_resp(401))
    result = fwd.process_ordering_key(db_session, "conv-1", client=saas.client(), now=T0, rng=random.Random(1))
    assert result.failed == 0 and result.retry_in and result.retry_in > 0
    row = _row(db_session, "e1")
    assert row.status == "pending" and row.attempts == 1 and row.next_attempt_at > T0
    assert row.last_error == "http_401" and row.payload["text"] == "keep"
    db_session.refresh(account)
    assert account.saas_degraded is True and account.saas_last_forward_status == "auth_rejected"


@skip_if_no_db
def test_401_then_202_succeeds_after_the_secret_is_fixed(db_session, account):
    _enqueue(db_session, account, "e1")
    fwd.process_ordering_key(db_session, "conv-1", client=FakeSaas(_resp(401)).client(), now=T0)
    # The operator enters the new secret in Many; the retry signs with it.
    delegation.apply_config(account, {"secret": "n" * 40}, now=T0)
    db_session.commit()
    ok = FakeSaas(_resp(202))
    later = _row(db_session, "e1").next_attempt_at + timedelta(seconds=1)
    result = fwd.process_ordering_key(db_session, "conv-1", client=ok.client(), now=later)
    assert result.sent == 1
    request = ok.requests[0]
    assert json.loads(request.content)["event_id"] == "e1"
    assert verify_signature(
        ["n" * 40], request.headers["x-osiris-timestamp"], request.headers["x-osiris-signature"], request.content
    )
    assert _row(db_session, "e1").status == "sent"
    db_session.refresh(account)
    assert account.saas_degraded is False and account.saas_last_forward_status == "sent_202"


@skip_if_no_db
def test_401_until_the_24h_budget_ends_fails_and_keeps_payload(db_session, account):
    _enqueue(db_session, account, "e1", text="keep")
    _row(db_session, "e1").created_at = T0 - timedelta(hours=24, minutes=1)
    db_session.commit()
    saas = FakeSaas(_resp(401))
    result = fwd.process_ordering_key(db_session, "conv-1", client=saas.client(), now=T0)
    assert result.failed == 1
    row = _row(db_session, "e1")
    assert row.status == "failed" and "retry_budget_exhausted" in row.last_error
    assert row.payload["text"] == "keep"
    assert saas.requests == []  # expired: nothing is sent (T1-P1)


@skip_if_no_db
def test_401_blocks_later_events_of_the_conversation_like_any_retry(db_session, account):
    _enqueue(db_session, account, "e1")
    _enqueue(db_session, account, "e2")
    saas = FakeSaas(_resp(401))
    fwd.process_ordering_key(db_session, "conv-1", client=saas.client(), now=T0)
    assert len(saas.requests) == 1 and _row(db_session, "e2").attempts == 0


@skip_if_no_db
def test_redirect_is_not_followed_and_is_permanent(db_session, account):
    _enqueue(db_session, account, "e1")
    saas = FakeSaas(httpx.Response(302, headers={"Location": "https://evil.example.com"}))
    fwd.process_ordering_key(db_session, "conv-1", client=saas.client(), now=T0)
    assert len(saas.requests) == 1 and _row(db_session, "e1").status == "failed"


@skip_if_no_db
def test_earlier_event_blocks_later_ones_of_the_same_conversation(db_session, account):
    _enqueue(db_session, account, "e1")
    _enqueue(db_session, account, "e2")
    _enqueue(db_session, account, "other", key="conv-2")
    saas = FakeSaas(_resp(500))
    fwd.process_ordering_key(db_session, "conv-1", client=saas.client(), now=T0)
    assert [json.loads(r.content)["event_id"] for r in saas.requests] == ["e1"]
    assert _row(db_session, "e2").status == "pending" and _row(db_session, "e2").attempts == 0

    # Another conversation is not blocked.
    ok = FakeSaas(_resp(202))
    fwd.process_ordering_key(db_session, "conv-2", client=ok.client(), now=T0)
    assert _row(db_session, "other").status == "sent"

    # Once e1 is delivered, e2 follows in order in the same pass.
    ok2 = FakeSaas(_resp(202))
    fwd.process_ordering_key(
        db_session, "conv-1", client=ok2.client(), now=_row(db_session, "e1").next_attempt_at + timedelta(seconds=1)
    )
    assert [json.loads(r.content)["event_id"] for r in ok2.requests] == ["e1", "e2"]


@skip_if_no_db
def test_event_older_than_24h_fails_and_the_queue_continues(db_session, account):
    _enqueue(db_session, account, "e1")
    _enqueue(db_session, account, "e2")
    first = _row(db_session, "e1")
    first.created_at = T0 - timedelta(hours=24, minutes=1)
    db_session.commit()
    saas = FakeSaas(_resp(202))
    result = fwd.process_ordering_key(db_session, "conv-1", client=saas.client(), now=T0)
    assert result.failed == 1 and result.sent == 1
    assert len(saas.requests) == 1  # only e2 was sent
    assert _row(db_session, "e1").status == "failed"
    assert "retry_budget_exhausted" in _row(db_session, "e1").last_error
    assert _row(db_session, "e2").status == "sent"


@skip_if_no_db
def test_disabling_drops_queued_events_and_nothing_is_sent(db_session, account):
    _enqueue(db_session, account, "e1")
    _enqueue(db_session, account, "e2")
    account.saas_delegation_enabled = False
    db_session.commit()
    saas = FakeSaas(_resp(202))
    result = fwd.process_ordering_key(db_session, "conv-1", client=saas.client(), now=T0)
    assert saas.requests == [] and result.sent == 0
    assert _row(db_session, "e1").status == "dropped" and _row(db_session, "e2").status == "dropped"
    assert _row(db_session, "e1").payload == {}


@skip_if_no_db
def test_drop_pending_leaves_sent_rows_alone(db_session, account):
    _enqueue(db_session, account, "e1")
    fwd.process_ordering_key(db_session, "conv-1", client=FakeSaas(_resp(202)).client(), now=T0)
    _enqueue(db_session, account, "e2")
    assert fwd.drop_pending(db_session, platform="whatsapp", channel_id=account.id) == 1
    db_session.commit()
    assert _row(db_session, "e1").status == "sent" and _row(db_session, "e2").status == "dropped"


@skip_if_no_db
def test_enqueue_is_idempotent_on_event_id(db_session, account):
    _enqueue(db_session, account, "e1")
    assert not fwd.enqueue_event(
        db_session, platform="whatsapp", channel=account, ordering_key="conv-1",
        event_id="e1", event_type="message.received", payload={},
    )
    assert db_session.query(SaasForwardEvent).filter_by(event_id="e1").count() == 1


@skip_if_no_db
def test_private_base_url_in_production_fails_event_without_a_request(db_session, account, monkeypatch):
    _enqueue(db_session, account, "e1")
    account.saas_base_url = "https://10.0.0.5"
    db_session.commit()
    monkeypatch.setattr(settings, "APP_ENV", "production")
    saas = FakeSaas(_resp(202))
    fwd.process_ordering_key(db_session, "conv-1", client=saas.client(), now=T0)
    assert saas.requests == [] and _row(db_session, "e1").status == "failed"


def test_backoff_grows_and_is_capped():
    rng = random.Random(0)
    values = [fwd.backoff_seconds(n, rng) for n in (1, 2, 4, 8, 20)]
    assert values[0] <= 5 and values[1] >= 5 and values[-1] <= fwd.BACKOFF_CAP_SECONDS
    assert values[3] > values[0]


@skip_if_no_db
def test_expired_event_is_not_delivered_even_if_the_saas_would_accept(db_session, account):
    _enqueue(db_session, account, "e1")
    _row(db_session, "e1").created_at = T0 - timedelta(hours=25)
    db_session.commit()
    saas = FakeSaas(_resp(202))
    result = fwd.process_ordering_key(db_session, "conv-1", client=saas.client(), now=T0)
    assert result.failed == 1 and result.sent == 0 and saas.requests == []


@skip_if_no_db
def test_wait_is_capped_at_the_deadline_then_the_event_fails_without_sending(db_session, account):
    _enqueue(db_session, account, "e1")
    _row(db_session, "e1").created_at = T0 - timedelta(hours=23, minutes=50)
    db_session.commit()
    saas = FakeSaas(_resp(429, {"Retry-After": "7200"}))
    fwd.process_ordering_key(db_session, "conv-1", client=saas.client(), now=T0)
    row = _row(db_session, "e1")
    assert row.status == "pending"
    assert row.next_attempt_at.astimezone(timezone.utc) <= T0 + timedelta(minutes=10, seconds=1)
    later = T0 + timedelta(minutes=11)
    result = fwd.process_ordering_key(db_session, "conv-1", client=FakeSaas(_resp(202)).client(), now=later)
    assert result.failed == 1 and _row(db_session, "e1").status == "failed"


@skip_if_no_db
def test_retry_after_over_an_hour_is_honoured(db_session, account):
    _enqueue(db_session, account, "e1")
    fwd.process_ordering_key(
        db_session, "conv-1", client=FakeSaas(_resp(429, {"Retry-After": "7200"})).client(), now=T0
    )
    assert _row(db_session, "e1").next_attempt_at.astimezone(timezone.utc) >= T0 + timedelta(seconds=7200)


@skip_if_no_db
def test_retry_after_http_date_and_503_are_honoured(db_session, account):
    from email.utils import format_datetime

    _enqueue(db_session, account, "e1")
    when = format_datetime(T0 + timedelta(seconds=900), usegmt=True)
    fwd.process_ordering_key(
        db_session, "conv-1", client=FakeSaas(_resp(503, {"Retry-After": when})).client(), now=T0
    )
    assert _row(db_session, "e1").next_attempt_at.astimezone(timezone.utc) >= T0 + timedelta(seconds=900)


def test_retry_after_parsing():
    assert fwd._retry_after(_resp(429, {"Retry-After": "30"}), T0) == 30
    assert fwd._retry_after(_resp(429, {"Retry-After": "garbage"}), T0) is None
    assert fwd._retry_after(_resp(429), T0) is None


# A16 privacy forwards are durable independently of the delegated chat switch.
def _enqueue_erasure(db, account, event_id="erasure-test", now=T0):
    fwd.enqueue_event(
        db, platform="whatsapp", channel=account, ordering_key="privacy-request",
        event_id=event_id, event_type="contact.erasure",
        payload={"version": 1, "event_id": event_id, "event_type": "contact.erasure",
                 "connection_id": account.saas_connection_id, "external_contact_id": "test-contact",
                 "occurred_at": now.isoformat()}, now=now,
    )
    db.commit()


def test_a16_disable_drops_ordinary_forward_but_preserves_and_sends_erasure(db_session, account):
    _enqueue(db_session, account, "ordinary")
    _enqueue_erasure(db_session, account)
    account.saas_delegation_enabled = False
    db_session.commit()
    assert fwd.drop_pending(db_session, platform="whatsapp", channel_id=account.id) == 1
    db_session.commit()
    assert _row(db_session, "ordinary").status == "dropped"
    assert _row(db_session, "erasure-test").status == "pending"
    server = FakeSaas(_resp(202))
    result = fwd.process_ordering_key(db_session, "privacy-request", client=server.client(), now=T0)
    assert result.sent == 1 and len(server.requests) == 1
    request = server.requests[0]
    body = json.loads(request.content)
    assert body["event_type"] == "contact.erasure"
    assert verify_signature([SECRET], request.headers["x-osiris-timestamp"], request.headers["x-osiris-signature"], request.content)
    assert _row(db_session, "erasure-test").payload == {}


@pytest.mark.parametrize("failure", ["missing_channel", "missing_secret", "changed_connection"])
def test_a16_missing_or_changed_signing_config_fails_without_sending(db_session, account, failure):
    _enqueue_erasure(db_session, account)
    if failure == "missing_channel":
        db_session.delete(account)
    elif failure == "missing_secret":
        account.saas_secret_encrypted = None
    else:
        account.saas_connection_id = str(uuid4())
    db_session.commit()
    server = FakeSaas(_resp(202))
    result = fwd.process_ordering_key(db_session, "privacy-request", client=server.client(), now=T0)
    assert result.failed == 1 and not server.requests
    row = _row(db_session, "erasure-test")
    assert row.status == "failed" and "erasure_operator_action_required" in row.last_error
    assert row.payload["external_contact_id"] == "test-contact"


def test_a16_revoked_401_retries_then_expiry_remains_operator_failure(db_session, account):
    _enqueue_erasure(db_session, account)
    row = _row(db_session, "erasure-test")
    row.created_at = T0
    account.saas_delegation_enabled = False
    db_session.commit()
    server = FakeSaas(_resp(401))
    result = fwd.process_ordering_key(db_session, "privacy-request", client=server.client(), now=T0)
    assert result.retry_in and _row(db_session, "erasure-test").status == "pending"
    expired = fwd.process_ordering_key(db_session, "privacy-request", client=server.client(), now=T0+timedelta(hours=24))
    assert expired.failed == 1 and len(server.requests) == 1
    assert _row(db_session, "erasure-test").status == "failed"
    assert "retry_budget_exhausted" in _row(db_session, "erasure-test").last_error
