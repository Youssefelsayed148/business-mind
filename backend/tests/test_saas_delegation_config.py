"""M-01: per-channel SaaS delegation settings (model defaults, URL/secret
validation, admin-only endpoints, secrets never echoed)."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.routes_auth import get_current_user
from app.core.config import settings
from app.core.security import hash_password
from app.models.facebook_page import FacebookPage
from app.models.instagram_account import InstagramAccount
from app.models.user import User
from app.models.user_workspace_membership import UserWorkspaceMembership
from app.models.whatsapp_account import WhatsappAccount
from app.models.workspace import Workspace
from app.services import saas_delegation_service as svc
from app.utils.crypto import decrypt_text
from tests.conftest import skip_if_no_db

SECRET = "s" * 40
SECRET_2 = "t" * 40
CONN = "123e4567-e89b-12d3-a456-426614174000"


def _channel():
    return SimpleNamespace(
        status="connected",
        saas_delegation_enabled=False,
        saas_connection_id=None,
        saas_base_url=None,
        saas_secret_encrypted=None,
        saas_previous_secret_encrypted=None,
        saas_previous_secret_expires_at=None,
        saas_last_forward_status=None,
        saas_last_forward_at=None,
        saas_degraded=False,
    )


@pytest.fixture(autouse=True)
def _encryption_key(monkeypatch):
    from cryptography.fernet import Fernet

    from app.utils import crypto

    monkeypatch.setattr(settings, "TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(crypto, "_fernet", None)
    yield
    monkeypatch.setattr(crypto, "_fernet", None)


# --- pure validation -------------------------------------------------------


def test_production_requires_https(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    with pytest.raises(svc.DelegationConfigError):
        svc.validate_base_url("http://8.8.8.8")
    assert svc.validate_base_url("https://8.8.8.8/") == "https://8.8.8.8"


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost",
        "https://127.0.0.1",
        "https://10.0.0.5",
        "https://192.168.1.1:8443",
        "https://169.254.169.254",
        "https://[::1]",
        "https://box.internal",
    ],
)
def test_production_rejects_private_and_loopback(monkeypatch, url):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    with pytest.raises(svc.DelegationConfigError):
        svc.validate_base_url(url)


def test_production_rejects_hostname_resolving_to_private(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(
        svc.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("10.1.2.3", 0))]
    )
    with pytest.raises(svc.DelegationConfigError):
        svc.validate_base_url("https://saas.example.com")


def test_production_accepts_public_hostname(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(
        svc.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0))]
    )
    assert svc.validate_base_url("https://saas.example.com/base/") == "https://saas.example.com/base"


def test_non_production_allows_http_localhost(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "test")
    assert svc.validate_base_url("http://localhost:9000") == "http://localhost:9000"


@pytest.mark.parametrize(
    "url", ["ftp://x.com", "https://user:pw@x.com", "https://x.com/?a=1", "https://x.com/#f", "not a url", ""]
)
def test_malformed_urls_rejected_everywhere(monkeypatch, url):
    monkeypatch.setattr(settings, "APP_ENV", "test")
    with pytest.raises(svc.DelegationConfigError):
        svc.validate_base_url(url)


def test_secret_rotation_keeps_previous_for_24h():
    ch = _channel()
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    svc.set_secret(ch, SECRET, now=now)
    assert ch.saas_previous_secret_encrypted is None
    assert decrypt_text(ch.saas_secret_encrypted) == SECRET
    assert ch.saas_secret_encrypted != SECRET

    svc.set_secret(ch, SECRET_2, now=now)
    assert ch.saas_previous_secret_expires_at == now + timedelta(hours=24)
    assert svc.get_secrets(ch, now=now + timedelta(hours=23)) == (SECRET_2, SECRET)
    assert svc.get_secrets(ch, now=now + timedelta(hours=25)) == (SECRET_2, None)


def test_short_secret_rejected():
    with pytest.raises(svc.DelegationConfigError):
        svc.set_secret(_channel(), "short")


def test_enable_requires_complete_config(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "test")
    ch = _channel()
    with pytest.raises(svc.DelegationConfigError):
        svc.apply_config(ch, {"saas_delegation_enabled": True})
    svc.apply_config(
        ch,
        {
            "saas_connection_id": f" {CONN.upper()} ",
            "saas_base_url": "https://saas.example.com",
            "secret": SECRET,
            "saas_delegation_enabled": True,
        },
    )
    assert ch.saas_delegation_enabled and ch.saas_connection_id == CONN
    ch.saas_degraded = True
    svc.apply_config(ch, {"saas_delegation_enabled": False})
    assert not ch.saas_delegation_enabled and not ch.saas_degraded


@pytest.mark.parametrize(
    "raw", [CONN.upper(), f"  {CONN}  ", CONN.replace("-", ""), "{" + CONN.upper() + "}", f"urn:uuid:{CONN}"]
)
def test_connection_id_is_stored_as_canonical_lowercase_uuid(raw):
    ch = _channel()
    svc.apply_config(ch, {"saas_connection_id": raw})
    assert ch.saas_connection_id == CONN


@pytest.mark.parametrize("raw", ["conn-1", "nope", "123e4567-e89b-12d3-a456", CONN + "0", "g" * 36])
def test_connection_id_garbage_is_rejected_and_nothing_changes(raw):
    ch = _channel()
    ch.saas_connection_id = CONN
    with pytest.raises(svc.DelegationConfigError, match="UUID"):
        svc.apply_config(ch, {"saas_connection_id": raw})
    assert ch.saas_connection_id == CONN


def test_connection_id_can_be_cleared():
    ch = _channel()
    svc.apply_config(ch, {"saas_connection_id": CONN})
    svc.apply_config(ch, {"saas_connection_id": "  "})
    assert ch.saas_connection_id is None


def test_response_never_contains_secret():
    ch = _channel()
    svc.set_secret(ch, SECRET)
    svc.set_secret(ch, SECRET_2)
    body = str(svc.config_response(ch))
    assert SECRET not in body and SECRET_2 not in body
    assert ch.saas_secret_encrypted not in body
    assert svc.config_response(ch)["secret_set"] is True


# --- DB / routes -----------------------------------------------------------


def _user(db, role):
    user = User(
        id=uuid4(),
        email=f"{uuid4()}@test.com",
        name="t",
        password_hash=hash_password("secret"),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture
def world(db_session, client):
    from app.main import app

    ws = Workspace(id=uuid4(), name="W", slug=f"w-{uuid4()}")
    other = Workspace(id=uuid4(), name="O", slug=f"o-{uuid4()}")
    db_session.add_all([ws, other])
    db_session.flush()
    ig = InstagramAccount(id=uuid4(), workspace_id=ws.id, ig_user_id=str(uuid4()))
    wa = WhatsappAccount(id=uuid4(), workspace_id=ws.id, phone_number_id=str(uuid4()))
    fb = FacebookPage(id=uuid4(), workspace_id=ws.id, page_id=str(uuid4()))
    db_session.add_all([ig, wa, fb])
    db_session.commit()

    def act_as(role, workspace=ws):
        user = _user(db_session, role)
        db_session.add(UserWorkspaceMembership(user_id=user.id, workspace_id=workspace.id, role=role))
        db_session.commit()
        app.dependency_overrides[get_current_user] = lambda: user
        return {"X-Workspace-Id": str(workspace.id)}

    yield SimpleNamespace(ws=ws, other=other, ig=ig, wa=wa, fb=fb, act_as=act_as)
    app.dependency_overrides.pop(get_current_user, None)


def _url(world, platform):
    return {
        "instagram": f"/instagram/accounts/{world.ig.id}/saas-delegation",
        "whatsapp": f"/whatsapp/accounts/{world.wa.id}/saas-delegation",
        "facebook": f"/facebook/accounts/{world.fb.id}/saas-delegation",
    }[platform]


@skip_if_no_db
def test_new_rows_default_to_delegation_off(world):
    for row in (world.ig, world.wa, world.fb):
        assert row.saas_delegation_enabled is False
        assert row.saas_degraded is False
        assert row.saas_secret_encrypted is None


@skip_if_no_db
@pytest.mark.parametrize("platform", ["instagram", "whatsapp", "facebook"])
def test_admin_can_configure_and_secret_is_not_echoed(world, client, platform):
    headers = world.act_as("admin")
    body = {
        "saas_connection_id": CONN.upper(),
        "saas_base_url": "https://saas.example.com",
        "secret": SECRET,
        "saas_delegation_enabled": True,
    }
    put = client.patch(_url(world, platform), json=body, headers=headers)
    assert put.status_code == 200, put.text
    assert put.json()["saas_delegation_enabled"] is True
    assert put.json()["secret_set"] is True
    assert put.json()["saas_connection_id"] == CONN
    assert SECRET not in put.text

    got = client.get(_url(world, platform), headers=headers)
    assert got.status_code == 200 and SECRET not in got.text
    assert "secret" not in got.json()

    off = client.patch(_url(world, platform), json={"saas_delegation_enabled": False}, headers=headers)
    assert off.json()["saas_delegation_enabled"] is False
    assert off.json()["secret_set"] is True


@skip_if_no_db
@pytest.mark.parametrize("platform", ["instagram", "whatsapp", "facebook"])
def test_non_admin_roles_forbidden(world, client, platform):
    for role in ("operator", "viewer"):
        headers = world.act_as(role)
        assert client.get(_url(world, platform), headers=headers).status_code == 403
        assert (
            client.patch(_url(world, platform), json={"saas_connection_id": "x"}, headers=headers).status_code
            == 403
        )


@skip_if_no_db
@pytest.mark.parametrize("platform", ["whatsapp", "facebook"])
def test_other_workspace_admin_gets_404(world, client, platform):
    headers = world.act_as("admin", workspace=world.other)
    assert client.get(_url(world, platform), headers=headers).status_code == 404


@skip_if_no_db
def test_enable_without_config_is_422_and_changes_nothing(world, client, db_session):
    headers = world.act_as("owner")
    resp = client.patch(_url(world, "whatsapp"), json={"saas_delegation_enabled": True}, headers=headers)
    assert resp.status_code == 422
    db_session.refresh(world.wa)
    assert world.wa.saas_delegation_enabled is False


@skip_if_no_db
@pytest.mark.parametrize("platform", ["instagram", "whatsapp", "facebook"])
def test_api_rejects_non_uuid_connection_id_with_422(world, client, db_session, platform):
    headers = world.act_as("admin")
    resp = client.patch(_url(world, platform), json={"saas_connection_id": "conn-1"}, headers=headers)
    assert resp.status_code == 422
    assert "UUID" in resp.json()["detail"]
    row = {"instagram": world.ig, "whatsapp": world.wa, "facebook": world.fb}[platform]
    db_session.refresh(row)
    assert row.saas_connection_id is None


@skip_if_no_db
def test_rotation_via_api_marks_previous_active(world, client):
    headers = world.act_as("admin")
    client.patch(_url(world, "facebook"), json={"secret": SECRET}, headers=headers)
    resp = client.patch(_url(world, "facebook"), json={"secret": SECRET_2}, headers=headers)
    assert resp.json()["previous_secret_active"] is True
    assert SECRET not in resp.text and SECRET_2 not in resp.text

