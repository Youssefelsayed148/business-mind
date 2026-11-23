"""F-02: failed events keep their payload for replay, the retention sweep,
failed-event counts in the delegation API and the admin-only retry."""

from datetime import timedelta
from uuid import uuid4

import pytest

from app.models.message import Message
from app.models.saas_forward_event import SaasForwardEvent
from app.models.saas_outbound_message import SaasOutboundMessage
from app.services import saas_delegation_service as delegation
from app.services import saas_forwarder as fwd
from tests.conftest import skip_if_no_db
from tests.test_saas_delegation_config import (  # noqa: F401 (fixtures)
    CONN,
    SECRET,
    _encryption_key,
    _url,
    world,
)
from tests.test_saas_forwarder import T0, FakeSaas, _enqueue, _resp, _row, account  # noqa: F401
from tests.test_saas_forwarder import _env  # noqa: F401
from tests.test_saas_messages import _world


def _age(db, event_id, *, status, days, payload=True):
    row = _row(db, event_id)
    row.status = status
    row.completed_at = T0 - timedelta(days=days)
    row.next_attempt_at = None
    if not payload:
        row.payload = {}
    db.commit()


# --- failed rows keep their payload ----------------------------------------


@skip_if_no_db
@pytest.mark.parametrize("code", [400, 403, 404, 422])
def test_permanent_4xx_failure_keeps_payload(db_session, account, code):
    _enqueue(db_session, account, "e1", text="keep me")
    fwd.process_ordering_key(db_session, "conv-1", client=FakeSaas(_resp(code)).client(), now=T0)
    row = _row(db_session, "e1")
    assert row.status == "failed"
    assert row.payload["text"] == "keep me"


@skip_if_no_db
def test_budget_exhaustion_and_config_error_keep_payload(db_session, account):
    _enqueue(db_session, account, "e1")
    _row(db_session, "e1").created_at = T0 - timedelta(hours=25)
    db_session.commit()
    fwd.process_ordering_key(db_session, "conv-1", client=FakeSaas(_resp(500)).client(), now=T0)
    assert _row(db_session, "e1").status == "failed" and _row(db_session, "e1").payload != {}

    _enqueue(db_session, account, "e2", key="conv-2")
    account.saas_base_url = "ftp://nope"
    db_session.commit()
    fwd.process_ordering_key(db_session, "conv-2", client=FakeSaas(_resp(202)).client(), now=T0)
    assert _row(db_session, "e2").status == "failed" and _row(db_session, "e2").payload != {}


@skip_if_no_db
def test_sent_and_dropped_rows_still_clear_their_payload(db_session, account):
    _enqueue(db_session, account, "e1")
    fwd.process_ordering_key(db_session, "conv-1", client=FakeSaas(_resp(202)).client(), now=T0)
    _enqueue(db_session, account, "e2", key="conv-2")
    fwd.drop_pending(db_session, platform="whatsapp", channel_id=account.id)
    db_session.commit()
    assert _row(db_session, "e1").payload == {} and _row(db_session, "e2").payload == {}


# --- retention sweep --------------------------------------------------------


@skip_if_no_db
def test_purge_clears_old_failed_payloads_and_deletes_old_terminal_rows(db_session, account):
    for event_id in ("f-8d", "f-3d", "f-31d", "s-31d", "s-5d", "d-31d", "p-40d", "f-8d-cleared"):
        _enqueue(db_session, account, event_id, key=f"k-{event_id}")
    _age(db_session, "f-8d", status="failed", days=8)
    _age(db_session, "f-3d", status="failed", days=3)
    _age(db_session, "f-31d", status="failed", days=31)
    _age(db_session, "s-31d", status="sent", days=31, payload=False)
    _age(db_session, "s-5d", status="sent", days=5, payload=False)
    _age(db_session, "d-31d", status="dropped", days=31, payload=False)
    _age(db_session, "f-8d-cleared", status="failed", days=8, payload=False)
    # a pending row is never touched, however old
    pending = _row(db_session, "p-40d")
    pending.created_at = T0 - timedelta(days=40)
    db_session.commit()

    result = fwd.purge_expired(db_session, now=T0)

    assert result.payloads_cleared == 2  # f-8d and f-31d (cleared before deletion order is irrelevant)
    assert result.events_deleted == 3  # f-31d, s-31d, d-31d
    ids = {r.event_id for r in db_session.query(SaasForwardEvent).filter(SaasForwardEvent.ordering_key.like("k-%"))}
    assert ids == {"f-8d", "f-3d", "s-5d", "p-40d", "f-8d-cleared"}
    assert _row(db_session, "f-8d").payload == {} and _row(db_session, "f-8d").status == "failed"
    assert _row(db_session, "f-3d").payload != {}
    assert _row(db_session, "p-40d").status == "pending" and _row(db_session, "p-40d").payload != {}


@skip_if_no_db
def test_purge_deletes_outbound_records_older_than_30_days_only(db_session):
    w = _world(db_session)
    message = db_session.query(Message).filter_by(conversation_id=w.conv.id).one()
    for message_id, days in (("old", 31), ("new", 6)):
        db_session.add(
            SaasOutboundMessage(
                connection_id=CONN, message_id=message_id, platform="whatsapp", channel_id=w.channel.id,
                kind="reply", message_pk=message.id, created_at=T0 - timedelta(days=days),
            )
        )
    db_session.commit()
    result = fwd.purge_expired(db_session, now=T0)
    assert result.outbound_deleted >= 1
    left = {r.message_id for r in db_session.query(SaasOutboundMessage).filter_by(connection_id=CONN)}
    assert "old" not in left and "new" in left


def test_retention_task_is_on_the_beat_schedule():
    from app.workers import saas_retention_tasks  # noqa: F401 (registers the task)
    from app.workers.celery_app import celery_app

    entry = celery_app.conf.beat_schedule["saas-retention-purge"]
    assert entry["task"] == "app.workers.saas_retention_tasks.purge_saas_data"
    assert entry["task"] in celery_app.tasks


# --- requeue ----------------------------------------------------------------


@skip_if_no_db
def test_requeue_restores_failed_rows_with_payload_and_same_event_id(db_session, account):
    _enqueue(db_session, account, "e1", text="again")
    _enqueue(db_session, account, "e2", key="conv-2")
    fwd.process_ordering_key(db_session, "conv-1", client=FakeSaas(_resp(400)).client(), now=T0)
    fwd.process_ordering_key(db_session, "conv-2", client=FakeSaas(_resp(400)).client(), now=T0)
    _age(db_session, "e2", status="failed", days=8, payload=False)  # payload already cleared

    assert fwd.count_failed(db_session, platform="whatsapp", channel_id=account.id) == (2, 1)
    assert fwd.requeue_failed(db_session, platform="whatsapp", channel_id=account.id, now=T0) == 1
    db_session.commit()

    row = _row(db_session, "e1")
    assert row.status == "pending" and row.event_id == "e1" and row.attempts == 0
    assert row.payload["text"] == "again" and row.completed_at is None and row.last_error is None
    assert _row(db_session, "e2").status == "failed"

    saas = FakeSaas(_resp(202))
    fwd.process_ordering_key(db_session, "conv-1", client=saas.client(), now=T0)
    assert _row(db_session, "e1").status == "sent"
    assert len(saas.requests) == 1


@skip_if_no_db
def test_requeued_event_gets_a_fresh_24h_budget(db_session, account):
    _enqueue(db_session, account, "e1")
    _row(db_session, "e1").created_at = T0 - timedelta(hours=30)
    db_session.commit()
    fwd.process_ordering_key(db_session, "conv-1", client=FakeSaas(_resp(500)).client(), now=T0)
    assert _row(db_session, "e1").status == "failed"
    fwd.requeue_failed(db_session, platform="whatsapp", channel_id=account.id, now=T0)
    db_session.commit()
    fwd.process_ordering_key(db_session, "conv-1", client=FakeSaas(_resp(500)).client(), now=T0)
    assert _row(db_session, "e1").status == "pending"  # retrying, not instantly failed again


@skip_if_no_db
def test_requeue_only_touches_the_given_channel(db_session, account):
    _enqueue(db_session, account, "e1")
    fwd.process_ordering_key(db_session, "conv-1", client=FakeSaas(_resp(400)).client(), now=T0)
    assert fwd.requeue_failed(db_session, platform="whatsapp", channel_id=uuid4(), now=T0) == 0
    assert fwd.requeue_failed(db_session, platform="facebook", channel_id=account.id, now=T0) == 0
    assert _row(db_session, "e1").status == "failed"


# --- API --------------------------------------------------------------------


def _delegate_wa(world, db_session):
    delegation.apply_config(
        world.wa,
        {
            "saas_connection_id": CONN,
            "saas_base_url": "https://saas.example.com",
            "secret": SECRET,
            "saas_delegation_enabled": True,
        },
    )
    db_session.commit()


def _failed(db_session, world, event_id, *, payload=True):
    fwd.enqueue_event(
        db_session, platform="whatsapp", channel=world.wa, ordering_key=f"k-{event_id}", event_id=event_id,
        event_type="message.received", payload={"text": "x"} if payload else {}, now=T0,
    )
    db_session.commit()
    _age(db_session, event_id, status="failed", days=1, payload=payload)


@skip_if_no_db
def test_api_reports_failed_event_counts(world, client, db_session):
    headers = world.act_as("admin")
    _delegate_wa(world, db_session)
    _failed(db_session, world, "a")
    _failed(db_session, world, "b", payload=False)
    body = client.get(_url(world, "whatsapp"), headers=headers).json()
    assert body["failed_events"] == 2 and body["retryable_failed_events"] == 1
    other = client.get(_url(world, "facebook"), headers=headers).json()
    assert other["failed_events"] == 0 and other["retryable_failed_events"] == 0


@skip_if_no_db
def test_api_retry_requeues_and_is_admin_only(world, client, db_session):
    _delegate_wa(world, db_session)
    _failed(db_session, world, "a")
    url = _url(world, "whatsapp") + "/retry-failed"

    for role in ("operator", "viewer"):
        assert client.post(url, headers=world.act_as(role)).status_code == 403
    assert _row(db_session, "a").status == "failed"

    resp = client.post(url, headers=world.act_as("admin"))
    assert resp.status_code == 200, resp.text
    assert resp.json()["requeued"] == 1 and resp.json()["retryable_failed_events"] == 0
    assert _row(db_session, "a").status == "pending"
    assert "secret" not in resp.json()


@skip_if_no_db
def test_api_retry_needs_delegation_enabled_and_correct_workspace(world, client, db_session):
    _delegate_wa(world, db_session)
    _failed(db_session, world, "a")
    world.wa.saas_delegation_enabled = False
    db_session.commit()
    url = _url(world, "whatsapp") + "/retry-failed"
    assert client.post(url, headers=world.act_as("admin")).status_code == 409
    assert _row(db_session, "a").status == "failed"
    assert client.post(url, headers=world.act_as("admin", workspace=world.other)).status_code == 404
