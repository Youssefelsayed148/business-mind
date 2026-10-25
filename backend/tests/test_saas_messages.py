"""M-03: POST /api/saas/messages - auth matrix, idempotency, validation and
delivery (window, length, channel state) through the existing send clients."""

import json
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.core.config import settings
from app.integrations.meta.messaging import MetaMessageResult
from app.models.conversation import Conversation
from app.models.facebook_page import FacebookPage
from app.models.instagram_account import InstagramAccount
from app.models.lead import Lead
from app.models.message import Message
from app.models.saas_outbound_message import SaasOutboundMessage
from app.models.whatsapp_account import WhatsappAccount
from app.models.whatsapp_contact import WhatsappContact
from app.models.workspace import Workspace
from app.services import saas_delegation_service as delegation
from app.services import saas_outbound
from app.services.saas_signing import sign_headers
from tests.conftest import skip_if_no_db

SECRET = "k" * 40
OLD_SECRET = "o" * 40
CONN = "conn-1"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    from cryptography.fernet import Fernet

    from app.utils import crypto

    monkeypatch.setattr(settings, "TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(crypto, "_fernet", None)
    monkeypatch.setattr(settings, "APP_ENV", "test")
    yield
    monkeypatch.setattr(crypto, "_fernet", None)


def _delegate(channel, connection=CONN):
    delegation.apply_config(
        channel,
        {
            "saas_connection_id": connection,
            "saas_base_url": "https://saas.example.com",
            "secret": SECRET,
            "saas_delegation_enabled": True,
        },
    )


def _world(db, platform="whatsapp", *, connection=CONN, window_open=True):
    ws = Workspace(id=uuid4(), name="W", slug=f"w-{uuid4()}")
    db.add(ws)
    db.flush()
    if platform == "whatsapp":
        channel = WhatsappAccount(id=uuid4(), workspace_id=ws.id, phone_number_id=f"p{uuid4().hex}")
        contact_id = "16315551234"
        lead = Lead(id=uuid4(), workspace_id=ws.id, whatsapp_account_id=channel.id, platform="whatsapp",
                    ig_user_id=contact_id, lead_source="cold_dm", status="new")
    elif platform == "facebook":
        channel = FacebookPage(id=uuid4(), workspace_id=ws.id, page_id=f"pg{uuid4().int % 10**9}")
        contact_id = "psid-1"
        lead = Lead(id=uuid4(), workspace_id=ws.id, platform="facebook", facebook_page_id=channel.id,
                    ig_user_id=contact_id, facebook_psid=contact_id, lead_source="cold_dm", status="new")
    else:
        channel = InstagramAccount(id=uuid4(), workspace_id=ws.id, ig_user_id=f"1784{uuid4().int % 10**9}")
        contact_id = "9000011"
        lead = Lead(id=uuid4(), workspace_id=ws.id, instagram_account_id=channel.id,
                    ig_user_id=contact_id, lead_source="cold_dm", status="new")
    _delegate(channel, connection)
    db.add(channel)
    db.flush()
    db.add(lead)
    db.flush()
    kwargs = {"instagram": {"instagram_account_id": channel.id},
              "whatsapp": {"platform": "whatsapp", "whatsapp_account_id": channel.id},
              "facebook": {"platform": "facebook", "facebook_page_id": channel.id}}[platform]
    conv = Conversation(id=uuid4(), workspace_id=ws.id, lead_id=lead.id, **kwargs)
    db.add(conv)
    inbound_at = datetime.now(timezone.utc) - (timedelta(hours=1) if window_open else timedelta(hours=30))
    db.add(Message(lead_id=lead.id, conversation_id=conv.id, direction="inbound", content="hi",
                   message_type="ai_conversation", status="received", created_at=inbound_at))
    if platform == "whatsapp":
        db.add(WhatsappContact(id=uuid4(), workspace_id=ws.id, whatsapp_account_id=channel.id,
                               wa_id=contact_id, lead_id=lead.id, last_inbound_at=inbound_at))
    db.commit()
    return SimpleNamespace(platform=platform, channel=channel, lead=lead, conv=conv, contact_id=contact_id)


def _body(w, **over):
    data = {"message_id": f"m-{uuid4().hex[:8]}", "connection_id": CONN, "external_contact_id": w.contact_id,
            "external_conversation_id": str(w.conv.id), "text": "Hello from the bot", "kind": "reply"}
    data.update(over)
    return data


def _post(client, data, *, secret=SECRET, connection=CONN, now=None, raw=None, headers_over=None):
    body = raw if raw is not None else json.dumps(data, separators=(",", ":")).encode()
    headers = sign_headers(connection, secret, body, now=now)
    headers["Content-Type"] = "application/json"
    headers.update(headers_over or {})
    return client.post("/api/saas/messages", content=body, headers=headers)


@pytest.fixture
def started():
    with patch("app.api.routes_saas_messages._start_delivery") as start:
        yield start


# --- accept -----------------------------------------------------------------


@skip_if_no_db
@pytest.mark.parametrize("platform", ["whatsapp", "facebook", "instagram"])
def test_valid_request_is_accepted_and_recorded(client, db_session, started, platform):
    w = _world(db_session, platform)
    data = _body(w)
    resp = _post(client, data)
    assert resp.status_code == 202
    message = db_session.get(Message, resp.json()["id"])
    assert message.direction == "outbound" and message.status == "queued" and message.content == data["text"]
    link = db_session.query(SaasOutboundMessage).filter_by(message_pk=message.id).one()
    assert (link.connection_id, link.message_id, link.platform, link.kind) == (CONN, data["message_id"], platform, "reply")
    started.assert_called_once_with(str(message.id))


@skip_if_no_db
def test_duplicate_message_id_returns_same_id_and_sends_once(client, db_session, started):
    w = _world(db_session)
    data = _body(w)
    first = _post(client, data)
    second = _post(client, data)
    assert first.status_code == second.status_code == 202 and first.json() == second.json()
    assert db_session.query(SaasOutboundMessage).filter_by(message_id=data["message_id"]).count() == 1
    assert db_session.query(Message).filter_by(conversation_id=w.conv.id, direction="outbound").count() == 1
    assert started.call_count == 1


@skip_if_no_db
@pytest.mark.parametrize("kind", ["reply", "agent", "handoff"])
def test_all_contract_kinds_accepted(client, db_session, started, kind):
    w = _world(db_session)
    assert _post(client, _body(w, kind=kind)).status_code == 202


# --- authentication ------------------------------------------------------------


def _assert_generic_401(resp):
    assert resp.status_code == 401 and resp.json() == {"detail": "unauthorized"}


@skip_if_no_db
def test_every_auth_failure_is_the_same_generic_401(client, db_session, started):
    w = _world(db_session)
    other = _world(db_session, connection="conn-2")
    other.channel.saas_delegation_enabled = False
    db_session.commit()
    data = _body(w)
    body = json.dumps(data, separators=(",", ":")).encode()
    good = sign_headers(CONN, SECRET, body)

    cases = {
        "no headers": client.post("/api/saas/messages", content=body),
        "wrong secret": _post(client, data, secret="z" * 40),
        "stale timestamp": _post(client, data, now=time.time() - 301),
        "future timestamp": _post(client, data, now=time.time() + 301),
        "unknown connection": _post(client, data, connection="nope"),
        "delegation disabled": _post(client, _body(other, connection_id="conn-2"), connection="conn-2"),
        "tampered body": client.post(
            "/api/saas/messages", content=body.replace(b"Hello", b"Jello"),
            headers={**good, "Content-Type": "application/json"}),
        "signature without prefix": client.post(
            "/api/saas/messages", content=body,
            headers={**good, "X-Osiris-Signature": good["X-Osiris-Signature"][7:]}),
        "body/header connection mismatch": _post(client, _body(w, connection_id="conn-9")),
        "oversized body": _post(client, None, raw=json.dumps(_body(w, text="x" * 70_000)).encode()),
    }
    for name, resp in cases.items():
        assert resp.status_code == 401, name
        assert resp.json() == {"detail": "unauthorized"}, name
    started.assert_not_called()
    assert db_session.query(SaasOutboundMessage).count() == 0


@skip_if_no_db
def test_previous_secret_accepted_during_grace_and_rejected_after(client, db_session, started):
    w = _world(db_session)
    delegation.set_secret(w.channel, "n" * 40)  # SECRET becomes the previous secret
    db_session.commit()
    assert _post(client, _body(w), secret=SECRET).status_code == 202
    assert _post(client, _body(w), secret="n" * 40).status_code == 202
    w.channel.saas_previous_secret_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    _assert_generic_401(_post(client, _body(w), secret=SECRET))
    assert _post(client, _body(w), secret="n" * 40).status_code == 202


@skip_if_no_db
def test_mounted_without_api_prefix_for_the_proxy(client, db_session, started):
    w = _world(db_session)
    body = json.dumps(_body(w), separators=(",", ":")).encode()
    headers = {**sign_headers(CONN, SECRET, body), "Content-Type": "application/json"}
    assert client.post("/saas/messages", content=body, headers=headers).status_code == 202


# --- validation -----------------------------------------------------------------


@skip_if_no_db
@pytest.mark.parametrize(
    "over",
    [{"text": ""}, {"kind": "followup"}, {"kind": "broadcast"}, {"message_id": ""}, {"message_id": "x" * 129}],
)
def test_malformed_body_is_422(client, db_session, started, over):
    w = _world(db_session)
    assert _post(client, _body(w, **over)).status_code == 422
    started.assert_not_called()


@skip_if_no_db
def test_not_json_is_422(client, db_session, started):
    _world(db_session)
    assert _post(client, None, raw=b"not json").status_code == 422


@skip_if_no_db
def test_unknown_conversation_contact_or_other_channels_conversation_is_404(client, db_session, started):
    w = _world(db_session)
    other = _world(db_session, connection="conn-2")
    assert _post(client, _body(w, external_conversation_id=str(uuid4()))).status_code == 404
    assert _post(client, _body(w, external_conversation_id="not-a-uuid")).status_code == 404
    assert _post(client, _body(w, external_contact_id="someone-else")).status_code == 404
    assert _post(client, _body(w, external_conversation_id=str(other.conv.id))).status_code == 404
    started.assert_not_called()


# --- delivery ---------------------------------------------------------------


def _accept(db, w, text="Hello from the bot"):
    return saas_outbound.accept_message(
        db, platform=w.platform, channel=w.channel, connection_id=CONN, message_id=f"m-{uuid4().hex[:8]}",
        external_contact_id=w.contact_id, external_conversation_id=str(w.conv.id), text=text, kind="reply",
    )


def _ok(pid="wamid.out"):
    return MetaMessageResult(success=True, provider_message_id=pid, raw_response={})


@pytest.fixture
def clients():
    """Patch the three Meta clients and token lookups; record calls."""
    wa, fb, ig = MagicMock(), MagicMock(), MagicMock()
    for c in (wa, fb, ig):
        c.return_value.send_text_message.return_value = _ok()
        c.return_value.send_direct_message.return_value = _ok()
    with patch.object(saas_outbound, "WhatsappClient", wa), patch.object(saas_outbound, "FacebookClient", fb), \
         patch.object(saas_outbound, "MetaMessagingClient", ig), \
         patch.object(saas_outbound.whatsapp_token_service, "get_decrypted_token", return_value="tok"), \
         patch.object(saas_outbound.facebook_token_service, "get_decrypted_token", return_value="tok"), \
         patch.object(saas_outbound.token_service, "get_decrypted_token", return_value="tok"):
        yield SimpleNamespace(wa=wa.return_value, fb=fb.return_value, ig=ig.return_value)


@skip_if_no_db
def test_whatsapp_delivery_uses_existing_text_send_and_marks_sent(db_session, clients):
    w = _world(db_session, "whatsapp")
    acc = _accept(db_session, w)
    assert saas_outbound.deliver_message(db_session, acc.message_pk) == "sent"
    clients.wa.send_text_message.assert_called_once_with("tok", w.channel.phone_number_id, "16315551234", "Hello from the bot")
    message = db_session.get(Message, acc.message_pk)
    assert message.status == "sent" and message.provider_message_id == "wamid.out"


@skip_if_no_db
def test_facebook_and_instagram_delivery_use_their_send_paths(db_session, clients):
    fb = _world(db_session, "facebook")
    assert saas_outbound.deliver_message(db_session, _accept(db_session, fb).message_pk) == "sent"
    clients.fb.send_direct_message.assert_called_once_with("tok", fb.channel.page_id, "psid-1", "Hello from the bot")
    ig = _world(db_session, "instagram")
    assert saas_outbound.deliver_message(db_session, _accept(db_session, ig).message_pk) == "sent"
    clients.ig.send_direct_message.assert_called_once_with("tok", ig.channel.ig_user_id, "9000011", "Hello from the bot")


@skip_if_no_db
@pytest.mark.parametrize("platform", ["whatsapp", "facebook", "instagram"])
def test_closed_window_fails_without_sending(db_session, clients, platform):
    w = _world(db_session, platform, window_open=False)
    acc = _accept(db_session, w)
    assert saas_outbound.deliver_message(db_session, acc.message_pk) == "failed"
    message = db_session.get(Message, acc.message_pk)
    assert message.status == "failed" and message.error_code == "window_closed"
    for c in (clients.wa, clients.fb, clients.ig):
        assert not c.send_text_message.called and not c.send_direct_message.called


@skip_if_no_db
def test_whatsapp_free_entry_window_counts_as_open(db_session, clients):
    w = _world(db_session, "whatsapp", window_open=False)
    contact = db_session.query(WhatsappContact).filter_by(whatsapp_account_id=w.channel.id).one()
    contact.free_entry_point_expires_at = datetime.now(timezone.utc) + timedelta(hours=10)
    db_session.commit()
    assert saas_outbound.deliver_message(db_session, _accept(db_session, w).message_pk) == "sent"


@skip_if_no_db
@pytest.mark.parametrize(
    "platform,text,ok",
    [
        ("whatsapp", "a" * 4096, True), ("whatsapp", "a" * 4097, False),
        ("facebook", "a" * 2000, True), ("facebook", "a" * 2001, False),
        ("instagram", "é" * 500, True),   # 1000 bytes
        ("instagram", "é" * 501, False),  # 1002 bytes though only 501 characters
    ],
)
def test_text_over_the_limit_fails_message_too_long_and_is_never_truncated(db_session, clients, platform, text, ok):
    w = _world(db_session, platform)
    acc = _accept(db_session, w, text=text)
    outcome = saas_outbound.deliver_message(db_session, acc.message_pk)
    message = db_session.get(Message, acc.message_pk)
    sent_calls = [c for cl in (clients.wa, clients.fb, clients.ig) for c in
                  (cl.send_text_message.call_args_list + cl.send_direct_message.call_args_list)]
    if ok:
        assert outcome == "sent" and sent_calls[0].args[-1] == text
    else:
        assert outcome == "failed" and message.error_code == "message_too_long" and not sent_calls


@skip_if_no_db
def test_disconnected_channel_or_delegation_off_fails_channel_disconnected(db_session, clients):
    w = _world(db_session)
    acc = _accept(db_session, w)
    w.channel.status = "disconnected"
    db_session.commit()
    assert saas_outbound.deliver_message(db_session, acc.message_pk) == "failed"
    assert db_session.get(Message, acc.message_pk).error_code == "channel_disconnected"
    assert not clients.wa.send_text_message.called

    w2 = _world(db_session)
    acc2 = _accept(db_session, w2)
    w2.channel.saas_delegation_enabled = False
    db_session.commit()
    assert saas_outbound.deliver_message(db_session, acc2.message_pk) == "failed"
    assert not clients.wa.send_text_message.called


@skip_if_no_db
def test_missing_token_fails_channel_disconnected(db_session, clients):
    w = _world(db_session)
    acc = _accept(db_session, w)
    with patch.object(saas_outbound.whatsapp_token_service, "get_decrypted_token", return_value=None):
        assert saas_outbound.deliver_message(db_session, acc.message_pk) == "failed"
    assert db_session.get(Message, acc.message_pk).error_code == "channel_disconnected"


@skip_if_no_db
def test_meta_failure_is_mapped_by_code_not_text(db_session, clients):
    w = _world(db_session)
    acc = _accept(db_session, w)
    clients.wa.send_text_message.return_value = MetaMessageResult(
        success=False, error_code="permission_error", error_message="boom",
        raw_response={"error": {"code": 131047, "error_subcode": None, "message": "re-engage"}},
    )
    assert saas_outbound.deliver_message(db_session, acc.message_pk) == "failed"
    message = db_session.get(Message, acc.message_pk)
    assert message.status == "failed" and message.error_code == "window_closed"
    assert "re-engage" not in message.error_message


@skip_if_no_db
def test_delivery_is_claimed_once(db_session, clients):
    w = _world(db_session)
    acc = _accept(db_session, w)
    assert saas_outbound.deliver_message(db_session, acc.message_pk) == "sent"
    assert saas_outbound.deliver_message(db_session, acc.message_pk) == "skipped"
    assert clients.wa.send_text_message.call_count == 1


@skip_if_no_db
def test_no_ai_service_involved(db_session, clients):
    from app.services import ai_service

    w = _world(db_session)
    with patch.object(ai_service, "generate_reply") as generate:
        saas_outbound.deliver_message(db_session, _accept(db_session, w).message_pk)
    assert not generate.called
