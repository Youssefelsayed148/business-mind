from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.campaign import Campaign
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


@skip_if_no_db
def test_patch_campaign_persists_ai_enabled(client: TestClient, db_session: Session):
    """Regression: the campaign edit form was PATCHing a hand-picked field
    allowlist that omitted ai_enabled / ai_handoff_after_turns / comment_reply_*,
    so checking "Let AI continue this campaign's conversations" never persisted.
    The PATCH endpoint itself must honour these fields when they are sent."""
    ws = Workspace(id=uuid4(), name="Default", slug="default")
    db_session.add(ws)
    user = User(
        id=uuid4(),
        email="aitoggle@test.com",
        name="AI Toggle",
        password_hash=hash_password("secret"),
        role="owner",  # needs manage_campaigns permission
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    acc = InstagramAccount(
        workspace_id=ws.id,
        ig_user_id="aitoggle_ig",
        ig_username="aitoggle",
    )
    db_session.add(acc)
    db_session.commit()
    store_encrypted_token(db_session, ws.id, acc.id, "fake_token")

    token = client.post(
        "/auth/login",
        data={"username": "aitoggle@test.com", "password": "secret"},
    ).json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}

    create_resp = client.post(
        "/campaigns",
        json={
            "instagram_account_id": str(acc.id),
            "name": "AI Toggle Campaign",
            "media_id": "m1",
            "message_template": "Hi {username}",
            "keywords": ["menu"],
            "match_type": "contains",
            "status": "draft",
        },
        headers=auth,
    )
    assert create_resp.status_code == 201
    campaign_id = create_resp.json()["id"]
    # ai_enabled defaults to false on create.
    assert create_resp.json()["ai_enabled"] is False

    patch_resp = client.patch(
        f"/campaigns/{campaign_id}",
        json={
            "ai_enabled": True,
            "ai_handoff_after_turns": 5,
            "comment_reply_enabled": True,
            "comment_reply_text": "Check your DMs",
        },
        headers=auth,
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["ai_enabled"] is True
    assert patch_resp.json()["ai_handoff_after_turns"] == 5
    assert patch_resp.json()["comment_reply_enabled"] is True

    # Re-fetch through the API...
    get_resp = client.get(f"/campaigns/{campaign_id}", headers=auth)
    assert get_resp.status_code == 200
    assert get_resp.json()["ai_enabled"] is True

    # ...and confirm it actually landed in the column, not just the response.
    db_session.expire_all()
    row = db_session.query(Campaign).filter(Campaign.id == campaign_id).first()
    assert row is not None
    assert row.ai_enabled is True
    assert row.ai_handoff_after_turns == 5
    assert row.comment_reply_enabled is True
