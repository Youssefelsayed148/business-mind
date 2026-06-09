from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.instagram_account import InstagramAccount
from app.models.meta_token import MetaToken
from app.models.user import User
from app.models.workspace import Workspace
from app.services.token_service import store_encrypted_token
from tests.conftest import skip_if_no_db


@skip_if_no_db
def test_simulate_returns_rendered_message(client: TestClient, db_session: Session):
    ws = Workspace(id=uuid4(), name="Default", slug="default")
    db_session.add(ws)
    user = User(
        id=uuid4(),
        email="sim@test.com",
        name="Sim User",
        password_hash=hash_password("secret"),
        role="user",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    acc = InstagramAccount(
        workspace_id=ws.id,
        ig_user_id="sim_ig",
        ig_username="simuser",
    )
    db_session.add(acc)
    db_session.commit()

    store_encrypted_token(db_session, ws.id, acc.id, "fake_token")

    token_resp = client.post(
        "/auth/login",
        data={"username": "sim@test.com", "password": "secret"},
    )
    token = token_resp.json()["access_token"]

    # Create campaign
    create_resp = client.post(
        "/campaigns",
        json={
            "instagram_account_id": str(acc.id),
            "name": "Sim Campaign",
            "media_id": "media_123",
            "message_template": "Hey {username}, here is the {keyword} link: {link}",
            "link_url": "https://example.com",
            "keywords": ["prompt"],
            "match_type": "contains",
            "status": "active",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create_resp.status_code == 201
    campaign_id = create_resp.json()["id"]

    # Simulate
    sim_resp = client.post(
        f"/campaigns/{campaign_id}/simulate",
        json={"comment_text": "I want the prompt", "username": "Ahmed"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert sim_resp.status_code == 200
    data = sim_resp.json()
    assert data["matched"] is True
    assert data["matched_keyword"] == "prompt"
    assert "Ahmed" in data["rendered_message"]
    assert "https://example.com" in data["rendered_message"]


@skip_if_no_db
def test_simulate_no_match(client: TestClient, db_session: Session):
    ws = Workspace(id=uuid4(), name="Default", slug="default")
    db_session.add(ws)
    user = User(
        id=uuid4(),
        email="sim2@test.com",
        name="Sim2",
        password_hash=hash_password("secret"),
        role="user",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    acc = InstagramAccount(
        workspace_id=ws.id,
        ig_user_id="sim2_ig",
        ig_username="sim2user",
    )
    db_session.add(acc)
    db_session.commit()

    store_encrypted_token(db_session, ws.id, acc.id, "fake_token")

    token_resp = client.post(
        "/auth/login",
        data={"username": "sim2@test.com", "password": "secret"},
    )
    token = token_resp.json()["access_token"]

    create_resp = client.post(
        "/campaigns",
        json={
            "instagram_account_id": str(acc.id),
            "name": "Sim2",
            "media_id": "m",
            "message_template": "Hi {username}",
            "keywords": ["ai"],
            "match_type": "exact",
            "status": "active",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    campaign_id = create_resp.json()["id"]

    sim_resp = client.post(
        f"/campaigns/{campaign_id}/simulate",
        json={"comment_text": "prompt", "username": "Test"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert sim_resp.status_code == 200
    data = sim_resp.json()
    assert data["matched"] is False
    assert data["matched_keyword"] is None
    assert data["rendered_message"] is None
