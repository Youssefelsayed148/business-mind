import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request

from app.authz import WorkspaceContext
from app.api import routes_facebook as fb, routes_whatsapp as wa, routes_meta as ig
from app.core.config import settings
from app.models.meta_authorization import MetaAuthorization
from app.services.meta_compliance import CHANNELS
from app.utils.crypto import decrypt_text
from tests.test_contact_erasure import world


@pytest.mark.parametrize("platform", ["facebook", "whatsapp", "instagram"])
@pytest.mark.parametrize(("reconnect", "fail", "pending"), [(False, False, False), (False, True, False),
    (True, False, False), (True, True, False), (True, False, True)])
def test_oauth_account_token_mapping_atomic(db_session, world, monkeypatch, platform, reconnect, fail, pending):
    module = {"facebook": fb, "whatsapp": wa, "instagram": ig}[platform]
    model, token, fk = CHANNELS[platform]
    channel = world.channels[("a", platform)]
    key = {"facebook": "page_id", "whatsapp": "phone_number_id", "instagram": "ig_user_id"}[platform]
    setattr(channel, key, "456")
    channel.status = "erasure_pending" if pending else "disconnected"
    channel_id = channel.id
    if reconnect:
        db_session.add(token(**{fk: channel_id}, access_token="old-encrypted"))
    else:
        db_session.delete(channel)
    db_session.commit()
    monkeypatch.setattr(settings, "FACEBOOK_APP_ID", "test-app")
    monkeypatch.setattr(settings, "META_APP_ID", "test-ig-app")
    state = json.dumps({"workspace_id": str(world.workspace.id)}) if platform == "instagram" else "1"
    monkeypatch.setattr(module, "_redis", lambda: SimpleNamespace(get=lambda _: state, delete=lambda _: None))
    monkeypatch.setattr(module, "_limit_mutation" if platform == "facebook" else "_limit_account_mutation", lambda _: None)
    debug = {"is_valid": True, "app_id": "test-app", "user_id": "123", "type": "USER"}
    if platform == "instagram":
        monkeypatch.setattr(module, "exchange_code_for_short_lived_token", AsyncMock(return_value={"access_token": "short", "user_id": "123"}))
        monkeypatch.setattr(module, "fetch_instagram_account_metadata", AsyncMock(return_value={"ig_user_id": "456", "username": "synthetic",
            "provider_user_id": "123", "provider_profile_id": "456"}))
    else:
        monkeypatch.setattr(module, "verify_user_access_token", AsyncMock(return_value=debug))
    monkeypatch.setattr(module, "exchange_for_long_lived_token", AsyncMock(return_value={"access_token": "long"}))
    if platform == "facebook":
        monkeypatch.setattr(module, "list_granted_pages", AsyncMock(return_value=[{"id": "456", "access_token": "long"}]))
        monkeypatch.setattr(module, "subscribe_app_to_page", AsyncMock())
        invoke = lambda: fb.facebook_connect_callback(fb.FacebookConnectCallback(access_token="short", state="state"), db_session,
                                                     WorkspaceContext(world.user, world.workspace.id))
    elif platform == "whatsapp":
        monkeypatch.setattr(module, "exchange_code_for_token", AsyncMock(return_value={"access_token": "short"}))
        monkeypatch.setattr(module, "fetch_waba_grant", AsyncMock(return_value=({"id": "789"}, [{"id": "456"}])))
        monkeypatch.setattr(module, "subscribe_app_to_waba", AsyncMock())
        monkeypatch.setattr(module, "fetch_phone_number_metadata", AsyncMock(return_value={"id": "456"}))
        invoke = lambda: wa.whatsapp_connect_callback(wa.WhatsappConnectCallback(code="code", state="state", phone_number_id="456", waba_id="789"),
                                                     db_session, WorkspaceContext(world.user, world.workspace.id))
    else:
        request = Request({"type": "http", "query_string": b"code=code&state=state", "headers": []})
        invoke = lambda: ig.meta_connect_callback(request, db_session)
    if pending:
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as rejected:
            asyncio.run(invoke())
        assert rejected.value.status_code == 409
        db_session.rollback()
        db_session.refresh(channel)
        assert channel.status == "erasure_pending"
        assert db_session.query(token).filter(getattr(token, fk) == channel.id).one().access_token == "old-encrypted"
    elif fail:
        original = module.save_grant
        def fail_after_mapping(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("synthetic transaction fault")
        monkeypatch.setattr(module, "save_grant", fail_after_mapping)
        with pytest.raises(RuntimeError):
            asyncio.run(invoke())
        db_session.rollback()
        assert db_session.query(MetaAuthorization).count() == 0
        existing = db_session.query(model).filter(getattr(model, key) == "456").one_or_none()
        assert (existing is not None) == reconnect
        if existing:
            assert existing.status == "disconnected"
            assert db_session.query(token).filter(getattr(token, fk) == existing.id).one().access_token == "old-encrypted"
    else:
        asyncio.run(invoke())
        account = db_session.query(model).filter(getattr(model, key) == "456").one()
        mapping = db_session.query(MetaAuthorization).filter_by(channel_id=account.id).one()
        assert decrypt_text(mapping.subject_encrypted) == "123"
        assert mapping.subject_namespace == ("app_user" if platform == "facebook" else "unresolved")
        assert decrypt_text(db_session.query(token).filter(getattr(token, fk) == account.id).one().access_token) == "long"
        if reconnect:
            assert account.id == channel_id
