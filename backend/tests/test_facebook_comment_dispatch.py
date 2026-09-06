"""Coverage for the Facebook comment-to-DM dispatch path: a comment matches
an active facebook_campaigns keyword -> a Lead + queued Message are created
and send_facebook_private_reply is dispatched — the Facebook equivalent of
the Instagram comment-handling loop in process_webhook_event.

process_webhook_event() is invoked directly (as a plain function) with the
test DB session injected via `_get_db`, and send_facebook_private_reply is
mocked — so these need only PostgreSQL, no Celery/Redis.
"""

from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.facebook_campaign import FacebookCampaign
from app.models.facebook_campaign_keyword import FacebookCampaignKeyword
from app.models.facebook_page import FacebookPage
from app.models.lead import Lead
from app.models.message import Message
from app.models.processed_webhook_event import ProcessedWebhookEvent  # noqa: F401 (register table)
from app.models.webhook_event import WebhookEvent
from app.models.workspace import Workspace
from tests.conftest import skip_if_no_db


def _fresh_page_id() -> str:
    return f"page_{uuid4().int % 10_000_000}"


def _seed(db: Session, page_id: str, *, keyword: str = "promo", cooldown_hours: int = 0):
    ws = Workspace(id=uuid4(), name="Default", slug=f"fb-{uuid4().hex[:8]}")
    db.add(ws)
    db.commit()

    page = FacebookPage(id=uuid4(), workspace_id=ws.id, page_id=page_id, page_name="Test Page")
    db.add(page)
    db.commit()

    campaign = FacebookCampaign(
        id=uuid4(),
        workspace_id=ws.id,
        facebook_page_id=page.id,
        name="Promo campaign",
        message_template="Hi {username}, here's your promo!",
        match_type="contains",
        status="active",
        cooldown_hours=cooldown_hours,
    )
    db.add(campaign)
    db.add(FacebookCampaignKeyword(id=uuid4(), campaign_id=campaign.id, normalized_keyword=keyword))
    db.commit()

    return ws, page, campaign


def _comment_payload(page_id: str, commenter_id: str, text: str, comment_id: str, post_id: str = "post_1") -> dict:
    return {
        "object": "page",
        "entry": [
            {
                "id": page_id,
                "changes": [
                    {
                        "field": "feed",
                        "value": {
                            "item": "comment",
                            "verb": "add",
                            "post_id": f"{page_id}_{post_id}",
                            "comment_id": comment_id,
                            "from": {"id": commenter_id, "name": "Commenter Name"},
                            "message": text,
                        },
                    }
                ],
            }
        ],
    }


def _run_webhook(db: Session, payload: dict):
    from app.workers import tasks

    event = WebhookEvent(
        provider="meta",
        external_event_id=uuid4().hex,
        event_type="page",
        payload=payload,
        processing_status="pending",
    )
    db.add(event)
    db.commit()

    orig_close = db.close
    db.close = lambda: None
    try:
        with patch.object(tasks, "_get_db", return_value=db), patch.object(
            tasks, "send_facebook_private_reply"
        ) as mock_send:
            tasks.process_webhook_event(str(event.id))
    finally:
        db.close = orig_close

    db.refresh(event)
    return event, mock_send


@skip_if_no_db
def test_matching_comment_creates_lead_and_queues_message(db_session: Session):
    page_id = _fresh_page_id()
    ws, page, campaign = _seed(db_session, page_id)

    event, mock_send = _run_webhook(
        db_session, _comment_payload(page_id, "commenter_1", "send me the promo please", "c1")
    )
    assert event.processing_status == "processed"
    assert mock_send.delay.called

    lead = db_session.query(Lead).filter(Lead.ig_user_id == "commenter_1").first()
    assert lead is not None
    assert lead.platform == "facebook"
    assert lead.facebook_page_id == page.id
    assert lead.ig_username == "Commenter Name"

    message = (
        db_session.query(Message)
        .filter(Message.facebook_campaign_id == campaign.id, Message.message_type == "final_delivery")
        .first()
    )
    assert message is not None
    assert message.lead_id == lead.id
    assert "promo" in message.rendered_body


@skip_if_no_db
def test_no_keyword_match_creates_no_message(db_session: Session):
    page_id = _fresh_page_id()
    _seed(db_session, page_id, keyword="promo")

    event, mock_send = _run_webhook(
        db_session, _comment_payload(page_id, "commenter_2", "totally unrelated comment", "c2")
    )
    assert event.processing_status == "processed"
    assert not mock_send.delay.called
    assert db_session.query(Lead).filter(Lead.ig_user_id == "commenter_2").first() is None


@skip_if_no_db
def test_cooldown_blocks_second_trigger(db_session: Session):
    page_id = _fresh_page_id()
    _seed(db_session, page_id, cooldown_hours=24)

    _run_webhook(db_session, _comment_payload(page_id, "commenter_3", "promo please", "c3"))
    event2, mock_send2 = _run_webhook(
        db_session, _comment_payload(page_id, "commenter_3", "promo again", "c4")
    )

    assert event2.processing_status == "processed"
    assert not mock_send2.delay.called
    messages = (
        db_session.query(Message)
        .join(Lead, Message.lead_id == Lead.id)
        .filter(Lead.ig_user_id == "commenter_3")
        .all()
    )
    assert len(messages) == 1


@skip_if_no_db
def test_page_not_found_is_skipped(db_session: Session):
    event, mock_send = _run_webhook(
        db_session, _comment_payload("nonexistent_page", "commenter_4", "promo", "c5")
    )
    assert event.processing_status == "processed"
    assert not mock_send.delay.called


@skip_if_no_db
def test_one_private_reply_per_comment_constraint_enforced(db_session: Session):
    """uq_message_facebook_campaign_comment_type is what actually enforces
    "one private reply per comment" for Facebook rows, since
    uq_message_campaign_comment_type never sees non-NULL values in its own
    columns for Facebook messages (both are FK'd to Instagram's tables)."""
    page_id = _fresh_page_id()
    ws, page, campaign = _seed(db_session, page_id)

    lead = Lead(
        id=uuid4(),
        workspace_id=ws.id,
        platform="facebook",
        facebook_page_id=page.id,
        instagram_account_id=None,
        ig_user_id="commenter_dup",
        lead_source="campaign",
        status="new",
    )
    db_session.add(lead)
    db_session.commit()

    from app.models.facebook_comment import FacebookComment

    comment = FacebookComment(
        id=uuid4(), facebook_page_id=page.id, comment_id="comment_dup", post_id="post_1"
    )
    db_session.add(comment)
    db_session.commit()

    db_session.add(
        Message(
            id=uuid4(),
            campaign_id=None,
            comment_id=None,
            facebook_campaign_id=campaign.id,
            facebook_comment_id=comment.id,
            lead_id=lead.id,
            rendered_body="first reply",
            message_type="final_delivery",
            status="queued",
        )
    )
    db_session.commit()

    db_session.add(
        Message(
            id=uuid4(),
            campaign_id=None,
            comment_id=None,
            facebook_campaign_id=campaign.id,
            facebook_comment_id=comment.id,
            lead_id=lead.id,
            rendered_body="second reply — should be rejected",
            message_type="final_delivery",
            status="queued",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
