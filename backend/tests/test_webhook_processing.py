from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.campaign import Campaign
from app.models.campaign_keyword import CampaignKeyword
from app.models.comment import Comment
from app.models.instagram_account import InstagramAccount
from app.models.lead import Lead
from app.models.message import Message
from app.models.meta_token import MetaToken
from app.models.user import User
from app.models.webhook_event import WebhookEvent
from app.models.workspace import Workspace
from app.services.token_service import store_encrypted_token
from app.services.message_service import create_queued_message
from tests.conftest import skip_if_no_db


def _make_signed_post(client, payload: dict):
    import hashlib
    import hmac
    import json

    from app.core.config import settings

    body = json.dumps(payload).encode("utf-8")
    sig = "sha256=" + hmac.new(settings.META_APP_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return client.post(
        "/webhooks/meta",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
    )


@skip_if_no_db
def test_webhook_event_enqueues_processing(client: TestClient, db_session: Session):
    with patch("app.api.routes_webhooks.process_webhook_event") as mock_task:
        payload = {
            "object": "instagram",
            "entry": [
                {
                    "id": "17841400000000000",
                    "changes": [
                        {
                            "field": "mentions",
                            "value": {
                                "item": "comment",
                                "media_id": "m1",
                                "comment_id": "c1",
                                "from": {"id": "u1", "username": "user1"},
                                "message": "test",
                            },
                        }
                    ],
                }
            ],
        }
        response = _make_signed_post(client, payload)
        assert response.status_code == 200
        assert response.json()["status"] == "received"
        assert mock_task.delay.called


@skip_if_no_db
def test_duplicate_webhook_does_not_duplicate_message(
    client: TestClient, db_session: Session
):
    ws = Workspace(id=uuid4(), name="Default", slug="default")
    db_session.add(ws)
    db_session.commit()

    acc = InstagramAccount(
        workspace_id=ws.id,
        ig_user_id="17841400000000000",
        ig_username="testacc",
    )
    db_session.add(acc)
    db_session.commit()

    store_encrypted_token(db_session, ws.id, acc.id, "fake_token")

    campaign = Campaign(
        id=uuid4(),
        workspace_id=ws.id,
        instagram_account_id=acc.id,
        name="Test",
        media_id="m1",
        message_template="Hi {username}",
        match_type="contains",
        status="active",
    )
    db_session.add(campaign)
    db_session.add(CampaignKeyword(id=uuid4(), campaign_id=campaign.id, normalized_keyword="test"))
    db_session.commit()

    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": "17841400000000000",
                "changes": [
                    {
                        "field": "mentions",
                        "value": {
                            "item": "comment",
                            "media_id": "m1",
                            "comment_id": "c_dup",
                            "from": {"id": "u1", "username": "user1"},
                            "message": "test",
                        },
                    }
                ],
            }
        ],
    }

    # First webhook
    _make_signed_post(client, payload)
    # Second identical webhook
    resp2 = _make_signed_post(client, payload)
    assert resp2.json()["status"] == "duplicate"

    # Only one message should exist
    messages = db_session.query(Message).filter(Message.campaign_id == campaign.id).all()
    assert len(messages) == 1


@skip_if_no_db
def test_comment_creates_comment_row(client: TestClient, db_session: Session):
    ws = Workspace(id=uuid4(), name="Default", slug="default")
    db_session.add(ws)
    db_session.commit()

    acc = InstagramAccount(
        workspace_id=ws.id,
        ig_user_id="17841400000000000",
        ig_username="testacc",
    )
    db_session.add(acc)
    db_session.commit()

    store_encrypted_token(db_session, ws.id, acc.id, "fake_token")

    campaign = Campaign(
        id=uuid4(),
        workspace_id=ws.id,
        instagram_account_id=acc.id,
        name="Test",
        media_id="m1",
        message_template="Hi {username}",
        match_type="contains",
        status="active",
    )
    db_session.add(campaign)
    db_session.add(CampaignKeyword(id=uuid4(), campaign_id=campaign.id, normalized_keyword="hello"))
    db_session.commit()

    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": "17841400000000000",
                "changes": [
                    {
                        "field": "mentions",
                        "value": {
                            "item": "comment",
                            "media_id": "m1",
                            "comment_id": "c_new",
                            "from": {"id": "u1", "username": "user1"},
                            "message": "hello world",
                        },
                    }
                ],
            }
        ],
    }

    _make_signed_post(client, payload)

    comment = db_session.query(Comment).filter(Comment.comment_id == "c_new").first()
    assert comment is not None
    assert comment.normalized_text == "hello world"


@skip_if_no_db
def test_matching_active_campaign_creates_queued_message(
    client: TestClient, db_session: Session
):
    ws = Workspace(id=uuid4(), name="Default", slug="default")
    db_session.add(ws)
    db_session.commit()

    acc = InstagramAccount(
        workspace_id=ws.id,
        ig_user_id="17841400000000000",
        ig_username="testacc",
    )
    db_session.add(acc)
    db_session.commit()

    store_encrypted_token(db_session, ws.id, acc.id, "fake_token")

    campaign = Campaign(
        id=uuid4(),
        workspace_id=ws.id,
        instagram_account_id=acc.id,
        name="Test",
        media_id="m1",
        message_template="Hi {username}",
        match_type="contains",
        status="active",
    )
    db_session.add(campaign)
    db_session.add(CampaignKeyword(id=uuid4(), campaign_id=campaign.id, normalized_keyword="hello"))
    db_session.commit()

    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": "17841400000000000",
                "changes": [
                    {
                        "field": "mentions",
                        "value": {
                            "item": "comment",
                            "media_id": "m1",
                            "comment_id": "c_match",
                            "from": {"id": "u1", "username": "user1"},
                            "message": "hello world",
                        },
                    }
                ],
            }
        ],
    }

    _make_signed_post(client, payload)

    messages = db_session.query(Message).filter(Message.campaign_id == campaign.id).all()
    assert len(messages) == 1
    assert messages[0].status == "queued"
    assert messages[0].message_type == "final_delivery"


@skip_if_no_db
def test_message_type_allows_follow_prompt_and_final_delivery(
    db_session: Session,
):
    ws = Workspace(id=uuid4(), name="Default", slug="message-type")
    db_session.add(ws)
    db_session.commit()

    acc = InstagramAccount(
        workspace_id=ws.id,
        ig_user_id="17841400000000009",
        ig_username="testacc",
    )
    db_session.add(acc)
    db_session.commit()

    campaign = Campaign(
        id=uuid4(),
        workspace_id=ws.id,
        instagram_account_id=acc.id,
        name="Follow",
        media_id="m1",
        message_template="Hi {username}",
        match_type="contains",
        status="active",
        delivery_mode="follow_prompt",
    )
    db_session.add(campaign)
    comment = Comment(
        id=uuid4(),
        instagram_account_id=acc.id,
        comment_id="c_message_type",
        ig_user_id="u1",
        ig_username="user1",
        message="hello",
        normalized_text="hello",
    )
    db_session.add(comment)
    lead = Lead(
        id=uuid4(),
        workspace_id=ws.id,
        instagram_account_id=acc.id,
        source_campaign_id=campaign.id,
        source_comment_id=comment.id,
        ig_user_id="u1",
        ig_username="user1",
    )
    db_session.add(lead)
    db_session.commit()

    prompt = create_queued_message(db_session, campaign.id, lead.id, comment.id, "Follow", "follow_prompt")
    final = create_queued_message(db_session, campaign.id, lead.id, comment.id, "Hi user1", "final_delivery")
    duplicate_final = create_queued_message(db_session, campaign.id, lead.id, comment.id, "Hi again", "final_delivery")

    assert prompt.id != final.id
    assert duplicate_final.id == final.id


@skip_if_no_db
def test_duplicate_comment_does_not_duplicate_message(
    client: TestClient, db_session: Session
):
    ws = Workspace(id=uuid4(), name="Default", slug="default")
    db_session.add(ws)
    db_session.commit()

    acc = InstagramAccount(
        workspace_id=ws.id,
        ig_user_id="17841400000000000",
        ig_username="testacc",
    )
    db_session.add(acc)
    db_session.commit()

    store_encrypted_token(db_session, ws.id, acc.id, "fake_token")

    campaign = Campaign(
        id=uuid4(),
        workspace_id=ws.id,
        instagram_account_id=acc.id,
        name="Test",
        media_id="m1",
        message_template="Hi {username}",
        match_type="contains",
        status="active",
    )
    db_session.add(campaign)
    db_session.add(CampaignKeyword(id=uuid4(), campaign_id=campaign.id, normalized_keyword="hello"))
    db_session.commit()

    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": "17841400000000000",
                "changes": [
                    {
                        "field": "mentions",
                        "value": {
                            "item": "comment",
                            "media_id": "m1",
                            "comment_id": "c_dup2",
                            "from": {"id": "u1", "username": "user1"},
                            "message": "hello world",
                        },
                    }
                ],
            }
        ],
    }

    # First webhook with this comment
    _make_signed_post(client, payload)
    # Second webhook with same comment_id but different webhook id
    payload2 = {
        "object": "instagram",
        "entry": [
            {
                "id": "17841400000000000",
                "changes": [
                    {
                        "field": "mentions",
                        "value": {
                            "item": "comment",
                            "media_id": "m1",
                            "comment_id": "c_dup2",
                            "from": {"id": "u1", "username": "user1"},
                            "message": "hello world again",
                        },
                    }
                ],
            }
        ],
    }
    _make_signed_post(client, payload2)

    messages = db_session.query(Message).filter(Message.campaign_id == campaign.id).all()
    assert len(messages) == 1


@skip_if_no_db
def test_lead_is_created_from_comment(client: TestClient, db_session: Session):
    ws = Workspace(id=uuid4(), name="Default", slug="default")
    db_session.add(ws)
    db_session.commit()

    acc = InstagramAccount(
        workspace_id=ws.id,
        ig_user_id="17841400000000000",
        ig_username="testacc",
    )
    db_session.add(acc)
    db_session.commit()

    store_encrypted_token(db_session, ws.id, acc.id, "fake_token")

    campaign = Campaign(
        id=uuid4(),
        workspace_id=ws.id,
        instagram_account_id=acc.id,
        name="Test",
        media_id="m1",
        message_template="Hi {username}",
        match_type="contains",
        status="active",
    )
    db_session.add(campaign)
    db_session.add(CampaignKeyword(id=uuid4(), campaign_id=campaign.id, normalized_keyword="hello"))
    db_session.commit()

    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": "17841400000000000",
                "changes": [
                    {
                        "field": "mentions",
                        "value": {
                            "item": "comment",
                            "media_id": "m1",
                            "comment_id": "c_lead",
                            "from": {"id": "u_lead", "username": "leaduser"},
                            "message": "hello",
                        },
                    }
                ],
            }
        ],
    }

    _make_signed_post(client, payload)

    lead = db_session.query(Lead).filter(Lead.ig_user_id == "u_lead").first()
    assert lead is not None
    assert lead.ig_username == "leaduser"


from unittest.mock import patch


@skip_if_no_db
def test_cooldown_prevents_message_queue(client: TestClient, db_session: Session):
    ws = Workspace(id=uuid4(), name="Default", slug="default")
    db_session.add(ws)
    db_session.commit()

    acc = InstagramAccount(
        workspace_id=ws.id,
        ig_user_id="17841400000000000",
        ig_username="testacc",
    )
    db_session.add(acc)
    db_session.commit()

    store_encrypted_token(db_session, ws.id, acc.id, "fake_token")

    campaign = Campaign(
        id=uuid4(),
        workspace_id=ws.id,
        instagram_account_id=acc.id,
        name="Test",
        media_id="m1",
        message_template="Hi {username}",
        match_type="contains",
        status="active",
        cooldown_hours=24,
    )
    db_session.add(campaign)
    db_session.add(CampaignKeyword(id=uuid4(), campaign_id=campaign.id, normalized_keyword="hello"))
    db_session.commit()

    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": "17841400000000000",
                "changes": [
                    {
                        "field": "mentions",
                        "value": {
                            "item": "comment",
                            "media_id": "m1",
                            "comment_id": "c_cool",
                            "from": {"id": "u_cool", "username": "cooluser"},
                            "message": "hello",
                        },
                    }
                ],
            }
        ],
    }

    _make_signed_post(client, payload)

    # Same user, same campaign, different comment -> should be blocked by cooldown
    payload2 = {
        "object": "instagram",
        "entry": [
            {
                "id": "17841400000000000",
                "changes": [
                    {
                        "field": "mentions",
                        "value": {
                            "item": "comment",
                            "media_id": "m1",
                            "comment_id": "c_cool2",
                            "from": {"id": "u_cool", "username": "cooluser"},
                            "message": "hello again",
                        },
                    }
                ],
            }
        ],
    }
    _make_signed_post(client, payload2)

    messages = db_session.query(Message).filter(Message.campaign_id == campaign.id).all()
    assert len(messages) == 1
