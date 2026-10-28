from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.automation_log import AutomationLog
from app.models.campaign import Campaign
from app.models.instagram_account import InstagramAccount
from app.models.meta_token import MetaToken
from app.models.user import User
from app.models.workspace import Workspace
from tests.conftest import skip_if_no_db


@skip_if_no_db
def test_list_instagram_accounts(client: TestClient, db_session: Session):
    ws = Workspace(id=uuid4(), name="Default", slug=f"ig-list-{uuid4()}")
    db_session.add(ws)
    user = User(
        id=uuid4(),
        email="iglist@test.com",
        name="IG List",
        password_hash=hash_password("secret"),
        role="user",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    acc = InstagramAccount(
        workspace_id=ws.id,
        ig_user_id="111222333",
        ig_username="listuser",
    )
    db_session.add(acc)
    db_session.commit()

    token_resp = client.post(
        "/auth/login",
        data={"username": "iglist@test.com", "password": "secret"},
    )
    token = token_resp.json()["access_token"]

    response = client.get(
        "/instagram/accounts",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert any(a["ig_user_id"] == "111222333" for a in data)


@skip_if_no_db
def test_get_instagram_account(client: TestClient, db_session: Session):
    ws = Workspace(id=uuid4(), name="Default", slug=f"ig-get-{uuid4()}")
    db_session.add(ws)
    user = User(
        id=uuid4(),
        email="igget@test.com",
        name="IG Get",
        password_hash=hash_password("secret"),
        role="user",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    acc = InstagramAccount(
        workspace_id=ws.id,
        ig_user_id="444555666",
        ig_username="getuser",
    )
    db_session.add(acc)
    db_session.commit()

    token_resp = client.post(
        "/auth/login",
        data={"username": "igget@test.com", "password": "secret"},
    )
    token = token_resp.json()["access_token"]

    response = client.get(
        f"/instagram/accounts/{acc.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ig_user_id"] == "444555666"


@skip_if_no_db
def test_disconnect_instagram_account(client: TestClient, db_session: Session):
    ws = Workspace(id=uuid4(), name="Default", slug=f"ig-disconnect-{uuid4()}")
    db_session.add(ws)
    user = User(
        id=uuid4(),
        email="igdel@test.com",
        name="IG Del",
        password_hash=hash_password("secret"),
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    acc = InstagramAccount(
        workspace_id=ws.id,
        ig_user_id="777888999",
        ig_username="deluser",
    )
    db_session.add(acc)
    db_session.commit()

    token_resp = client.post(
        "/auth/login",
        data={"username": "igdel@test.com", "password": "secret"},
    )
    token = token_resp.json()["access_token"]

    response = client.delete(
        f"/instagram/accounts/{acc.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "disconnected"
    assert data["username"] == "deluser"

    db_session.refresh(acc)
    assert acc.status == "disconnected"
    assert acc.ig_username == "deluser"


@skip_if_no_db
def test_disconnect_instagram_account_is_idempotent(client: TestClient, db_session: Session):
    ws = Workspace(id=uuid4(), name="Default", slug=f"ig-idempotent-{uuid4()}")
    db_session.add(ws)
    user = User(
        id=uuid4(),
        email="igidempotent@test.com",
        name="IG Idempotent",
        password_hash=hash_password("secret"),
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    acc = InstagramAccount(
        workspace_id=ws.id,
        ig_user_id="101202303",
        ig_username="testcompany",
    )
    db_session.add(acc)
    db_session.commit()

    token_resp = client.post(
        "/auth/login",
        data={"username": "igidempotent@test.com", "password": "secret"},
    )
    token = token_resp.json()["access_token"]

    for _ in range(2):
        response = client.delete(
            f"/instagram/accounts/{acc.id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "disconnected"
        assert data["username"] == "testcompany"

    db_session.refresh(acc)
    assert acc.status == "disconnected"
    assert acc.ig_username == "testcompany"


@skip_if_no_db
def test_disconnect_pauses_active_campaigns_and_overview_count(client: TestClient, db_session: Session):
    ws = Workspace(id=uuid4(), name="Default", slug=f"ig-lifecycle-{uuid4()}")
    db_session.add(ws)
    user = User(
        id=uuid4(),
        email="iglifecycle@test.com",
        name="IG Lifecycle",
        password_hash=hash_password("secret"),
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    acc = InstagramAccount(
        workspace_id=ws.id,
        ig_user_id="404505606",
        ig_username="testcompany",
        status="connected",
    )
    db_session.add(acc)
    db_session.commit()

    token_row = MetaToken(
        instagram_account_id=acc.id,
        access_token="encrypted-placeholder",
        token_type="long_lived",
        status="active",
    )
    active_campaign = Campaign(
        workspace_id=ws.id,
        instagram_account_id=acc.id,
        name="Active campaign",
        media_id="media_1",
        message_template="Hi",
        status="active",
    )
    draft_campaign = Campaign(
        workspace_id=ws.id,
        instagram_account_id=acc.id,
        name="Draft campaign",
        media_id="media_2",
        message_template="Hi",
        status="draft",
    )
    db_session.add_all([token_row, active_campaign, draft_campaign])
    db_session.commit()

    token_resp = client.post(
        "/auth/login",
        data={"username": "iglifecycle@test.com", "password": "secret"},
    )
    token = token_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    overview_before = client.get("/stats/overview", headers=headers)
    assert overview_before.status_code == 200
    active_campaigns_before = overview_before.json()["active_campaigns"]

    response = client.delete(f"/instagram/accounts/{acc.id}", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "disconnected"
    assert data["username"] == "testcompany"

    db_session.refresh(acc)
    db_session.refresh(token_row)
    db_session.refresh(active_campaign)
    db_session.refresh(draft_campaign)
    assert acc.status == "disconnected"
    assert acc.ig_username == "testcompany"
    assert token_row.status == "expired"
    assert active_campaign.status == "paused"
    assert draft_campaign.status == "draft"

    overview_after = client.get("/stats/overview", headers=headers)
    assert overview_after.status_code == 200
    assert overview_after.json()["active_campaigns"] == active_campaigns_before - 1

    actions = {
        row.action
        for row in db_session.query(AutomationLog)
        .filter(AutomationLog.instagram_account_id == acc.id)
        .all()
    }
    assert "account_disconnected" in actions
    assert "campaign_paused_account_disconnected" in actions


@skip_if_no_db
def test_reconnect_restores_account_and_token_without_reactivating_campaigns(
    client: TestClient, db_session: Session, monkeypatch
):
    ws = Workspace(id=uuid4(), name="Default", slug="default")
    db_session.add(ws)
    user = User(
        id=uuid4(),
        email="igreconnect@test.com",
        name="IG Reconnect",
        password_hash=hash_password("secret"),
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    acc = InstagramAccount(
        workspace_id=ws.id,
        ig_user_id="707808909",
        ig_username="testcompany",
        status="disconnected",
    )
    db_session.add(acc)
    db_session.flush()

    campaign = Campaign(
        workspace_id=ws.id,
        instagram_account_id=acc.id,
        name="Paused campaign",
        media_id="media_1",
        message_template="Hi",
        status="paused",
    )
    db_session.add(campaign)
    db_session.commit()

    token_row = MetaToken(
        instagram_account_id=acc.id,
        access_token="encrypted-placeholder",
        token_type="long_lived",
        status="expired",
    )
    db_session.add(token_row)
    db_session.commit()

    token_resp = client.post(
        "/auth/login",
        data={"username": "igreconnect@test.com", "password": "secret"},
    )
    token = token_resp.json()["access_token"]

    response = client.post(
        f"/instagram/accounts/{acc.id}/reconnect",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    from unittest.mock import AsyncMock
    from urllib.parse import parse_qs, urlparse
    from app.api import routes_meta

    state = parse_qs(urlparse(response.json()["oauth_url"]).query)["state"][0]
    db_session.refresh(acc)
    db_session.refresh(token_row)
    assert acc.status == "disconnected"
    assert token_row.status == "expired"
    monkeypatch.setattr(routes_meta, "exchange_code_for_short_lived_token", AsyncMock(return_value={"access_token": "short-test-token"}))
    monkeypatch.setattr(routes_meta, "exchange_for_long_lived_token", AsyncMock(return_value={"access_token": "long-test-token", "expires_in": 5184000}))
    monkeypatch.setattr(routes_meta, "fetch_instagram_account_metadata", AsyncMock(return_value={"ig_user_id": acc.ig_user_id, "username": "testcompany", "account_type": "BUSINESS"}))
    callback = client.get("/meta/connect/callback", params={"code": "test-code", "state": state}, follow_redirects=False)
    assert callback.status_code == 307
    assert "reconnected=true" in callback.headers["location"]

    db_session.refresh(acc)
    db_session.refresh(token_row)
    db_session.refresh(campaign)
    assert acc.status == "connected"
    assert acc.ig_username == "testcompany"
    # Reconnect stores a new token; the expired historical row stays expired.
    from app.services.token_service import get_decrypted_token
    assert token_row.status == "expired"
    active_token = db_session.query(MetaToken).filter(
        MetaToken.instagram_account_id == acc.id, MetaToken.status == "active"
    ).one()
    assert active_token.id != token_row.id
    assert get_decrypted_token(db_session, acc.id) == "long-test-token"
    assert campaign.status == "paused"

    from app.models.audit_log import AuditLog
    log = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.entity_id == acc.id,
            AuditLog.action == "account_reconnect_initiated",
        )
        .first()
    )
    assert log is not None
