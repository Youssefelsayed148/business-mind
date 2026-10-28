"""M-05: channel.status derivation, push on transitions + heartbeat, and the
signed health pull."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.models.facebook_token import FacebookToken
from app.models.meta_token import MetaToken
from app.models.saas_forward_event import SaasForwardEvent
from app.models.webhook_health import WebhookHealth
from app.models.whatsapp_token import WhatsappToken
from app.services import saas_health
from app.services.saas_signing import sign_headers
from tests.conftest import skip_if_no_db
from tests.test_saas_messages import CONN, OLD_SECRET, SECRET, _env, _world  # noqa: F401

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
TOKEN = {"instagram": (MetaToken, "instagram_account_id"), "whatsapp": (WhatsappToken, "whatsapp_account_id"),
         "facebook": (FacebookToken, "facebook_page_id")}


@pytest.fixture(autouse=True)
def _no_broker():
    with patch("app.services.saas_inbound._kick") as kick:
        yield kick


def _token(db, w, status="active", expires_at=None):
    model, fk = TOKEN[w.platform]
    db.add(model(**{fk: w.channel.id}, access_token="enc", status=status, expires_at=expires_at))
    db.commit()


def _webhook_failures(db, n):
    db.query(WebhookHealth).delete()
    db.add(WebhookHealth(provider="meta", consecutive_failures=n))
    db.commit()


def _events(db, w):
    db.expire_all()
    return (db.query(SaasForwardEvent).filter_by(channel_id=w.channel.id, event_type="channel.status")
            .order_by(SaasForwardEvent.seq).all())


# --- derivation --------------------------------------------------------------


@skip_if_no_db
@pytest.mark.parametrize("platform", ["whatsapp", "facebook", "instagram"])
def test_healthy_channel_is_connected(db_session, platform):
    w = _world(db_session, platform)
    _webhook_failures(db_session, 0)
    _token(db_session, w, expires_at=NOW + timedelta(days=30))
    assert saas_health.current_health(db_session, platform, w.channel, NOW) == {"status": "connected"}


@skip_if_no_db
@pytest.mark.parametrize("platform", ["whatsapp", "facebook", "instagram"])
def test_each_status_is_derived_from_existing_state(db_session, platform):
    w = _world(db_session, platform)
    _webhook_failures(db_session, 0)
    cur = lambda: saas_health.current_health(db_session, platform, w.channel, NOW)  # noqa: E731

    assert cur()["status"] == "token_expired"  # connected channel, no token at all

    _token(db_session, w, expires_at=NOW + timedelta(days=3))
    got = cur()
    assert got["status"] == "token_expiring" and got["expires_at"] == "2026-11-04T12:00:00Z"

    _webhook_failures(db_session, 3)
    assert cur()["status"] == "webhook_unhealthy"
    _webhook_failures(db_session, 2)
    assert cur()["status"] == "token_expiring"

    model, fk = TOKEN[platform]
    db_session.query(model).delete()
    _token(db_session, w, status="expired")
    assert cur()["status"] == "token_expired"

    db_session.query(model).delete()
    _token(db_session, w, expires_at=NOW - timedelta(minutes=1))
    assert cur()["status"] == "token_expired"

    w.channel.status = "disconnected"
    db_session.commit()
    assert cur()["status"] == "disconnected"


@skip_if_no_db
def test_expiring_soon_status_flag_counts(db_session):
    w = _world(db_session)
    _webhook_failures(db_session, 0)
    _token(db_session, w, status="expiring_soon")
    assert saas_health.current_health(db_session, "whatsapp", w.channel, NOW)["status"] == "token_expiring"


# --- push ----------------------------------------------------------------------


@skip_if_no_db
def test_push_on_transition_only_then_heartbeat(db_session, _no_broker):
    w = _world(db_session)
    _webhook_failures(db_session, 0)
    _token(db_session, w, expires_at=NOW + timedelta(days=30))

    assert saas_health.sync_channel(db_session, "whatsapp", w.channel, now=NOW) is True  # first push
    assert saas_health.sync_channel(db_session, "whatsapp", w.channel, now=NOW + timedelta(minutes=2)) is False
    assert saas_health.sync_channel(db_session, "whatsapp", w.channel, now=NOW + timedelta(hours=4)) is False

    w.channel.status = "disconnected"
    db_session.commit()
    assert saas_health.sync_channel(db_session, "whatsapp", w.channel, now=NOW + timedelta(hours=4, minutes=1)) is True
    # heartbeat even with no change
    assert saas_health.sync_channel(db_session, "whatsapp", w.channel, now=NOW + timedelta(hours=9, minutes=2)) is True

    events = _events(db_session, w)
    assert [e.payload["status"] for e in events] == ["connected", "disconnected", "disconnected"]
    first = events[0].payload
    assert first["version"] == 1 and first["event_type"] == "channel.status"
    assert first["connection_id"] == CONN and first["occurred_at"] == "2026-11-01T12:00:00Z"
    assert len({e.event_id for e in events}) == 3
    assert all(e.ordering_key == f"channel:whatsapp:{w.channel.id}" for e in events)
    assert _no_broker.called


@skip_if_no_db
def test_sweep_pushes_for_delegated_channels_only(db_session):
    w = _world(db_session)
    off = _world(db_session, connection="33333333-3333-4333-8333-333333333333")
    off.channel.saas_delegation_enabled = False
    db_session.commit()
    _webhook_failures(db_session, 0)
    assert saas_health.sync_all(db_session, now=NOW) >= 1
    assert len(_events(db_session, w)) == 1
    assert _events(db_session, off) == []


@skip_if_no_db
def test_disabled_channel_pushes_nothing(db_session):
    w = _world(db_session)
    w.channel.saas_delegation_enabled = False
    db_session.commit()
    assert saas_health.sync_channel(db_session, "whatsapp", w.channel, now=NOW, force=True) is False
    assert _events(db_session, w) == []


@skip_if_no_db
def test_health_events_are_delivered_by_the_signed_forwarder(db_session):
    import httpx

    from app.services import saas_forwarder as fwd

    w = _world(db_session)
    _webhook_failures(db_session, 0)
    saas_health.sync_channel(db_session, "whatsapp", w.channel, now=NOW)
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(202, json={"status": "accepted"})

    # created_at is the DB clock; align it with the fixed test clock (24 h budget).
    from app.models.saas_forward_event import SaasForwardEvent

    db_session.query(SaasForwardEvent).update({"created_at": NOW})
    db_session.commit()
    client_ = httpx.Client(transport=httpx.MockTransport(handler))
    res = fwd.process_ordering_key(db_session, f"channel:whatsapp:{w.channel.id}", client=client_, now=NOW)
    assert res.sent == 1 and len(seen) == 1
    assert seen[0].headers["X-Osiris-Connection"] == CONN
    assert b'"event_type":"channel.status"' in seen[0].content.replace(b" ", b"")


# --- pull ----------------------------------------------------------------------


def _get(client, *, secret=SECRET, connection=CONN, path_id=None, now=None, headers_over=None, content=b""):
    headers = sign_headers(connection, secret, content, now=now)
    headers.update(headers_over or {})
    return client.request("GET", f"/api/saas/connections/{path_id or connection}/health", headers=headers, content=content)


@skip_if_no_db
@pytest.mark.parametrize("platform", ["whatsapp", "facebook", "instagram"])
def test_signed_pull_returns_status_and_checked_at(client, db_session, platform):
    w = _world(db_session, platform)
    _webhook_failures(db_session, 0)
    _token(db_session, w, expires_at=datetime.now(timezone.utc) + timedelta(days=2))
    resp = _get(client)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "token_expiring" and "expires_at" in body and body["checked_at"].endswith("Z")


@skip_if_no_db
def test_pull_matches_push_derivation(client, db_session):
    w = _world(db_session)
    _webhook_failures(db_session, 3)
    _token(db_session, w, expires_at=datetime.now(timezone.utc) + timedelta(days=30))
    assert _get(client).json()["status"] == "webhook_unhealthy"


@skip_if_no_db
def test_pull_accepts_previous_secret_during_rotation(client, db_session):
    from app.services import saas_delegation_service as delegation

    w = _world(db_session)
    delegation.set_secret(w.channel, "n" * 40)
    db_session.commit()
    assert _get(client, secret=SECRET).status_code == 200  # previous, still in grace
    assert _get(client, secret="n" * 40).status_code == 200
    assert _get(client, secret=OLD_SECRET).status_code == 401


@skip_if_no_db
def test_pull_failures_are_one_generic_401(client, db_session):
    w = _world(db_session)
    other = _world(db_session, connection="22222222-2222-4222-8222-222222222222")
    other.channel.saas_delegation_enabled = False
    db_session.commit()
    stale = (datetime.now(timezone.utc) - timedelta(minutes=6)).timestamp()
    cases = {
        "bad secret": _get(client, secret="z" * 40),
        "stale": _get(client, now=stale),
        "unknown connection": _get(client, connection="nope"),
        "delegation off": _get(client, connection="22222222-2222-4222-8222-222222222222"),
        "path mismatch": _get(client, path_id="22222222-2222-4222-8222-222222222222"),
        "body present": _get(client, content=b"{}"),
        "no signature": client.get(f"/api/saas/connections/{CONN}/health"),
        "bad signature header": _get(client, headers_over={"X-Osiris-Signature": "sha256=00"}),
    }
    for name, resp in cases.items():
        assert resp.status_code == 401 and resp.json() == {"detail": "unauthorized"}, name


@skip_if_no_db
def test_pull_without_public_prefix_is_also_mounted(client, db_session):
    _world(db_session)
    headers = sign_headers(CONN, SECRET, b"")
    assert client.get(f"/saas/connections/{CONN}/health", headers=headers).status_code == 200


@skip_if_no_db
def test_pull_makes_no_outbound_call_and_queues_nothing(client, db_session):
    w = _world(db_session)
    with patch("httpx.Client.send") as send, patch("httpx.AsyncClient.send") as asend:
        assert _get(client).status_code == 200
    assert not send.called and not asend.called
    assert _events(db_session, w) == []


# --- enabling pushes an initial status ------------------------------------------


@skip_if_no_db
def test_enabling_delegation_pushes_initial_status(db_session):
    from app.api.routes_saas_delegation import _update
    from app.schemas.saas_delegation import SaasDelegationUpdate

    w = _world(db_session)
    w.channel.saas_delegation_enabled = False
    db_session.commit()
    user = type("U", (), {"id": uuid4()})()
    with patch("app.api.routes_saas_delegation._limit"), patch("app.api.routes_saas_delegation.write_audit_log"):
        _update(db_session, w.channel, user, SaasDelegationUpdate(saas_delegation_enabled=True), "whatsapp_account", "whatsapp")
    assert len(_events(db_session, w)) == 1
