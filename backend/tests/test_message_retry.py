from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.campaign import Campaign
from app.models.campaign_keyword import CampaignKeyword
from app.models.instagram_account import InstagramAccount
from app.models.message import Message
from app.models.meta_token import MetaToken
from app.models.user import User
from app.models.workspace import Workspace
from app.services.token_service import store_encrypted_token
from tests.conftest import skip_if_no_db


@skip_if_no_db
def test_retry_endpoint_accepts_failed_message(client: TestClient, db_session: Session):
    ws = Workspace(id=uuid4(), name="Default", slug="default")
    db_session.add(ws)
    user = User(
        id=uuid4(),
        email="retry@test.com",
        name="Retry User",
        password_hash=hash_password("secret"),
        role="user",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    acc = InstagramAccount(
        workspace_id=ws.id,
        ig_user_id="ig_retry",
        ig_username="retryacc",
    )
    db_session.add(acc)
    db_session.commit()

    campaign = Campaign(
        id=uuid4(),
        workspace_id=ws.id,
        instagram_account_id=acc.id,
        name="Retry",
        media_id="m1",
        message_template="Hi",
        match_type="contains",
        status="active",
    )
    db_session.add(campaign)
    db_session.commit()

    msg = Message(
        id=uuid4(),
        campaign_id=campaign.id,
        lead_id=uuid4(),
        status="failed",
        retryable=True,
        rendered_body="test",
    )
    db_session.add(msg)
    db_session.commit()

    token_resp = client.post(
        "/auth/login",
        data={"username": "retry@test.com", "password": "secret"},
    )
    token = token_resp.json()["access_token"]

    with patch("app.api.routes_messages.send_private_reply") as mock_task:
        response = client.post(
            f"/messages/{msg.id}/retry",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "retry_enqueued"
        assert mock_task.delay.called


@skip_if_no_db
def test_retry_endpoint_rejects_sent_message(client: TestClient, db_session: Session):
    ws = Workspace(id=uuid4(), name="Default", slug="default")
    db_session.add(ws)
    user = User(
        id=uuid4(),
        email="retry2@test.com",
        name="Retry2",
        password_hash=hash_password("secret"),
        role="user",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    acc = InstagramAccount(
        workspace_id=ws.id,
        ig_user_id="ig_retry2",
        ig_username="retryacc2",
    )
    db_session.add(acc)
    db_session.commit()

    campaign = Campaign(
        id=uuid4(),
        workspace_id=ws.id,
        instagram_account_id=acc.id,
        name="Retry2",
        media_id="m1",
        message_template="Hi",
        match_type="contains",
        status="active",
    )
    db_session.add(campaign)
    db_session.commit()

    msg = Message(
        id=uuid4(),
        campaign_id=campaign.id,
        lead_id=uuid4(),
        status="sent",
        rendered_body="test",
    )
    db_session.add(msg)
    db_session.commit()

    token_resp = client.post(
        "/auth/login",
        data={"username": "retry2@test.com", "password": "secret"},
    )
    token = token_resp.json()["access_token"]

    response = client.post(
        f"/messages/{msg.id}/retry",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422


@skip_if_no_db
def test_retry_endpoint_rejects_expired_message(client: TestClient, db_session: Session):
    ws = Workspace(id=uuid4(), name="Default", slug="default")
    db_session.add(ws)
    user = User(
        id=uuid4(),
        email="retry3@test.com",
        name="Retry3",
        password_hash=hash_password("secret"),
        role="user",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    acc = InstagramAccount(
        workspace_id=ws.id,
        ig_user_id="ig_retry3",
        ig_username="retryacc3",
    )
    db_session.add(acc)
    db_session.commit()

    campaign = Campaign(
        id=uuid4(),
        workspace_id=ws.id,
        instagram_account_id=acc.id,
        name="Retry3",
        media_id="m1",
        message_template="Hi",
        match_type="contains",
        status="active",
    )
    db_session.add(campaign)
    db_session.commit()

    msg = Message(
        id=uuid4(),
        campaign_id=campaign.id,
        lead_id=uuid4(),
        status="expired",
        rendered_body="test",
    )
    db_session.add(msg)
    db_session.commit()

    token_resp = client.post(
        "/auth/login",
        data={"username": "retry3@test.com", "password": "secret"},
    )
    token = token_resp.json()["access_token"]

    response = client.post(
        f"/messages/{msg.id}/retry",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422
