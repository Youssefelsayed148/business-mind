"""Coverage for cold-DM AI conversations: an unknown IG user DMs a business
account directly, with no prior campaign interaction (no Lead, no
source_campaign_id).

The campaign-triggered continuation path (test_ai_continuation_dispatch.py)
must be entirely unaffected by these changes — test_existing_campaign_lead_
unaffected_by_cold_dm_changes pins that.

process_webhook_event() is invoked directly (as a plain function) with the
test DB session injected via `_get_db`, and process_ai_conversation_turn is
mocked — so these need only PostgreSQL, no Celery/Redis.
"""

from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.automation_log import AutomationLog
from app.models.campaign import Campaign
from app.models.conversation import Conversation
from app.models.instagram_account import InstagramAccount
from app.models.lead import Lead
from app.models.message import Message
from app.models.processed_webhook_event import ProcessedWebhookEvent  # noqa: F401 (register table)
from app.models.user import User
from app.models.webhook_event import WebhookEvent
from app.models.workspace import Workspace
from app.services import ai_service
from tests.conftest import skip_if_no_db


def _fresh_ids() -> tuple[str, str]:
    tag = uuid4().int % 10_000_000
    return f"178414{tag:010d}", f"900001{tag:010d}"


def _seed_account(
    db: Session,
    account_ig: str,
    *,
    ai_enabled: bool,
    ai_cold_dm_enabled: bool,
    business_vertical: str = "general",
) -> tuple[Workspace, InstagramAccount]:
    ws = Workspace(id=uuid4(), name="Default", slug=f"cold-{uuid4().hex[:8]}")
    db.add(ws)
    db.commit()

    acc = InstagramAccount(
        id=uuid4(),
        workspace_id=ws.id,
        ig_user_id=account_ig,
        ig_username="popeye_restaurant_",
        business_vertical=business_vertical,
        ai_enabled=ai_enabled,
        ai_cold_dm_enabled=ai_cold_dm_enabled,
        ai_daily_message_cap=100,
        ai_handoff_after_turns=8,
    )
    db.add(acc)
    db.commit()
    return ws, acc


def _dm_payload(account_ig: str, sender_ig: str, text: str, mid: str) -> dict:
    return {
        "object": "instagram",
        "entry": [
            {
                "id": account_ig,
                "time": 1788012570939,
                "messaging": [
                    {
                        "sender": {"id": sender_ig},
                        "recipient": {"id": account_ig},
                        "timestamp": 1788012570939,
                        "message": {"mid": mid, "text": text},
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
        event_type="instagram",
        payload=payload,
        processing_status="pending",
    )
    db.add(event)
    db.commit()

    orig_close = db.close
    db.close = lambda: None
    try:
        with patch.object(tasks, "_get_db", return_value=db), patch.object(
            tasks, "process_ai_conversation_turn"
        ) as mock_turn:
            tasks.process_webhook_event(str(event.id))
    finally:
        db.close = orig_close

    db.refresh(event)
    return event, mock_turn


def _logs(db: Session, action: str, account_id):
    return (
        db.query(AutomationLog)
        .filter(AutomationLog.action == action, AutomationLog.instagram_account_id == account_id)
        .all()
    )


@skip_if_no_db
def test_cold_dm_creates_lead_and_dispatches_when_enabled(db_session: Session):
    account_ig, sender_ig = _fresh_ids()
    _, acc = _seed_account(db_session, account_ig, ai_enabled=True, ai_cold_dm_enabled=True)

    event, mock_turn = _run_webhook(
        db_session, _dm_payload(account_ig, sender_ig, "do you deliver on fridays?", "mid.cold1")
    )
    assert event.processing_status == "processed"

    lead = (
        db_session.query(Lead)
        .filter(Lead.instagram_account_id == acc.id, Lead.ig_user_id == sender_ig)
        .first()
    )
    assert lead is not None
    assert lead.lead_source == "cold_dm"
    assert lead.source_campaign_id is None

    conversation = (
        db_session.query(Conversation).filter(Conversation.lead_id == lead.id).first()
    )
    assert conversation is not None
    assert conversation.campaign_id is None
    assert conversation.status == "bot_active"

    inbound = (
        db_session.query(Message)
        .filter(Message.conversation_id == conversation.id, Message.direction == "inbound")
        .all()
    )
    assert len(inbound) == 1
    assert inbound[0].campaign_id is None
    assert inbound[0].content == "do you deliver on fridays?"

    mock_turn.delay.assert_called_once_with(str(conversation.id), str(inbound[0].id))

    assert len(_logs(db_session, "cold_dm_lead_created", acc.id)) == 1
    dispatched = _logs(db_session, "ai_continuation_dispatched", acc.id)
    assert len(dispatched) == 1
    assert dispatched[0].details["conversation_id"] == str(conversation.id)
    assert dispatched[0].details["lead_source"] == "cold_dm"


@skip_if_no_db
def test_cold_dm_skipped_when_account_toggle_disabled(db_session: Session):
    """Account AI on, cold-DM toggle off: no Lead created, correct skip log."""
    account_ig, sender_ig = _fresh_ids()
    _, acc = _seed_account(db_session, account_ig, ai_enabled=True, ai_cold_dm_enabled=False)

    event, mock_turn = _run_webhook(
        db_session, _dm_payload(account_ig, sender_ig, "hi there", "mid.cold2")
    )
    assert event.processing_status == "processed"

    assert (
        db_session.query(Lead)
        .filter(Lead.instagram_account_id == acc.id, Lead.ig_user_id == sender_ig)
        .first()
        is None
    )
    mock_turn.delay.assert_not_called()

    skipped = _logs(db_session, "ai_continuation_skipped", acc.id)
    assert len(skipped) == 1
    assert skipped[0].details["reason"] == "no_lead_and_cold_dm_disabled"


@skip_if_no_db
def test_cold_dm_skipped_when_account_ai_disabled(db_session: Session):
    """Account-level AI off entirely: same fail-closed outcome, different
    reason (the pre-existing account_ai_disabled gate fires first)."""
    account_ig, sender_ig = _fresh_ids()
    _, acc = _seed_account(db_session, account_ig, ai_enabled=False, ai_cold_dm_enabled=True)

    event, mock_turn = _run_webhook(
        db_session, _dm_payload(account_ig, sender_ig, "hello", "mid.cold3")
    )
    assert event.processing_status == "processed"

    assert (
        db_session.query(Lead)
        .filter(Lead.instagram_account_id == acc.id, Lead.ig_user_id == sender_ig)
        .first()
        is None
    )
    mock_turn.delay.assert_not_called()

    skipped = _logs(db_session, "ai_continuation_skipped", acc.id)
    assert len(skipped) == 1
    assert skipped[0].details["reason"] == "account_ai_disabled"


@skip_if_no_db
def test_existing_campaign_lead_unaffected_by_cold_dm_changes(db_session: Session):
    """A lead with lead_source='campaign' still follows the exact old path:
    campaign conversation, campaign_id populated, dispatched — even though the
    account's cold-DM toggle is OFF."""
    account_ig, sender_ig = _fresh_ids()
    ws, acc = _seed_account(db_session, account_ig, ai_enabled=True, ai_cold_dm_enabled=False)

    campaign = Campaign(
        id=uuid4(),
        workspace_id=ws.id,
        instagram_account_id=acc.id,
        name="burger post",
        message_template="Hi {username}",
        match_type="contains",
        status="active",
        ai_enabled=True,
        ai_handoff_after_turns=8,
    )
    db_session.add(campaign)
    db_session.commit()

    lead = Lead(
        id=uuid4(),
        workspace_id=ws.id,
        instagram_account_id=acc.id,
        ig_user_id=sender_ig,
        ig_username="hungry_lead",
        source_campaign_id=campaign.id,
        lead_source="campaign",
        status="new",
    )
    db_session.add(lead)
    db_session.commit()

    event, mock_turn = _run_webhook(
        db_session, _dm_payload(account_ig, sender_ig, "what are the hours", "mid.camp1")
    )
    assert event.processing_status == "processed"

    conversation = (
        db_session.query(Conversation)
        .filter(Conversation.lead_id == lead.id, Conversation.campaign_id == campaign.id)
        .first()
    )
    assert conversation is not None
    assert conversation.campaign_id == campaign.id

    inbound = (
        db_session.query(Message)
        .filter(Message.conversation_id == conversation.id, Message.direction == "inbound")
        .all()
    )
    assert len(inbound) == 1
    assert inbound[0].campaign_id == campaign.id

    mock_turn.delay.assert_called_once_with(str(conversation.id), str(inbound[0].id))

    dispatched = _logs(db_session, "ai_continuation_dispatched", acc.id)
    assert len(dispatched) == 1
    assert dispatched[0].campaign_id == campaign.id

    # No cold-DM lead was created, no cold-DM log emitted.
    assert _logs(db_session, "cold_dm_lead_created", acc.id) == []
    assert (
        db_session.query(Lead)
        .filter(Lead.instagram_account_id == acc.id, Lead.lead_source == "cold_dm")
        .count()
        == 0
    )


def test_cold_dm_applies_vertical_safety_instructions():
    """The non-overridable, server-side vertical safety instruction is injected
    on the cold-DM prompt path identically to the campaign path."""
    clinical = InstagramAccount(
        id=uuid4(),
        workspace_id=uuid4(),
        ig_user_id="acc_clinical",
        business_vertical="clinical",
        ai_business_profile="A physiotherapy clinic in Cairo.",
        ai_tone_instructions="Warm and reassuring.",
    )
    restaurant = InstagramAccount(
        id=uuid4(),
        workspace_id=uuid4(),
        ig_user_id="acc_restaurant",
        business_vertical="restaurant",
        ai_business_profile="A burger place.",
    )

    clinical_expected = ai_service._VERTICAL_SAFETY_INSTRUCTIONS["clinical"]
    restaurant_expected = ai_service._VERTICAL_SAFETY_INSTRUCTIONS["restaurant"]

    cold_clinical = ai_service.build_cold_dm_system_prompt(clinical)
    cold_restaurant = ai_service.build_cold_dm_system_prompt(restaurant)

    assert clinical_expected in cold_clinical
    assert restaurant_expected in cold_restaurant
    # Identical safety text on both paths.
    fake_campaign = type("C", (), {"name": "SpringPromo"})()
    campaign_prompt = ai_service.build_system_prompt(clinical, fake_campaign)
    assert clinical_expected in campaign_prompt

    # The campaign path names its originating campaign; the cold-DM path does
    # not carry any campaign/offer context.
    assert "started from the campaign: SpringPromo" in campaign_prompt
    assert "SpringPromo" not in cold_clinical
    assert "started from the campaign" not in cold_clinical
    assert ai_service._HANDOFF_INSTRUCTION in cold_clinical


@skip_if_no_db
def test_patch_account_persists_ai_cold_dm_enabled(client: TestClient, db_session: Session):
    """Dashboard save regression: the new "Also let AI answer unsolicited DMs"
    checkbox must actually persist to InstagramAccount.ai_cold_dm_enabled.
    Same shape as test_patch_campaign_persists_ai_enabled."""
    ws = Workspace(id=uuid4(), name="Default", slug=f"cold-patch-{uuid4().hex[:8]}")
    db_session.add(ws)
    user = User(
        id=uuid4(),
        email="colddm@test.com",
        name="Cold DM",
        password_hash=hash_password("secret"),
        role="owner",  # needs manage_accounts
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    acc = InstagramAccount(
        id=uuid4(),
        workspace_id=ws.id,
        ig_user_id=f"acc-{uuid4().hex[:10]}",
        ig_username="popeye_restaurant_",
    )
    db_session.add(acc)
    db_session.commit()
    # Default is false on create.
    assert acc.ai_cold_dm_enabled is False

    token = client.post(
        "/auth/login", data={"username": "colddm@test.com", "password": "secret"}
    ).json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}

    patch_resp = client.patch(
        f"/instagram/accounts/{acc.id}/ai-settings",
        json={"ai_enabled": True, "ai_cold_dm_enabled": True},
        headers=auth,
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["ai_enabled"] is True
    assert patch_resp.json()["ai_cold_dm_enabled"] is True

    get_resp = client.get(f"/instagram/accounts/{acc.id}", headers=auth)
    assert get_resp.status_code == 200
    assert get_resp.json()["ai_cold_dm_enabled"] is True

    db_session.expire_all()
    row = db_session.query(InstagramAccount).filter(InstagramAccount.id == acc.id).first()
    assert row is not None
    assert row.ai_cold_dm_enabled is True
