"""M-06: Take Over / Resume Bot are refused on delegated channels (409 with a
stable code), unchanged elsewhere, and Many's own AI gates (turn limit, daily
cap, campaign ai_enabled) have no effect on a delegated channel."""

from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.api.routes_auth import get_current_user
from app.models.campaign import Campaign
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.models.saas_forward_event import SaasForwardEvent
from app.services import conversation_service
from tests.conftest import skip_if_no_db
from tests.test_saas_delegation_dispatch import (  # noqa: F401
    _env, _fb_page, _ig_account, _run, _wa_account, fb_payload, ig_payload, wa_payload,
)
from tests.test_saas_delegation_config import _user
from tests.test_saas_messages import CONN, _world  # noqa: F401


@pytest.fixture(autouse=True)
def _no_broker():
    with patch("app.services.saas_inbound._kick"):
        yield


@pytest.fixture
def as_admin(db_session):
    from app.main import app
    from app.models.user_workspace_membership import UserWorkspaceMembership  # noqa: F401

    user = _user(db_session, "admin")
    app.dependency_overrides[get_current_user] = lambda: user
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _conv(w, status="bot_active"):
    w.conv.status = status
    return w.conv


@skip_if_no_db
@pytest.mark.parametrize("platform", ["whatsapp", "facebook", "instagram"])
@pytest.mark.parametrize("action", ["take-over", "resume-bot"])
def test_delegated_channel_refuses_with_stable_409(client, db_session, as_admin, platform, action):
    w = _world(db_session, platform)
    conv = _conv(w, "bot_active" if action == "take-over" else "handed_off")
    db_session.commit()
    resp = client.post(f"/conversations/{conv.id}/{action}")
    assert resp.status_code == 409
    assert resp.json()["detail"] == {"code": "CHANNEL_MANAGED_BY_SAAS", "message": "Managed in the SaaS inbox"}
    db_session.refresh(conv)
    assert conv.status == ("bot_active" if action == "take-over" else "handed_off")
    assert conv.handoff_reason is None


@skip_if_no_db
@pytest.mark.parametrize("platform", ["whatsapp", "facebook", "instagram"])
def test_delegation_off_keeps_take_over_and_resume_working(client, db_session, as_admin, platform):
    w = _world(db_session, platform)
    w.channel.saas_delegation_enabled = False
    db_session.commit()
    r1 = client.post(f"/conversations/{w.conv.id}/take-over")
    assert r1.status_code == 200 and r1.json()["status"] == "handed_off" and r1.json()["managed_by_saas"] is False
    r2 = client.post(f"/conversations/{w.conv.id}/resume-bot")
    assert r2.status_code == 200 and r2.json()["status"] == "bot_active"


@skip_if_no_db
def test_rollback_disabling_delegation_restores_the_actions(client, db_session, as_admin):
    w = _world(db_session, "whatsapp")
    assert client.post(f"/conversations/{w.conv.id}/take-over").status_code == 409
    w.channel.saas_delegation_enabled = False
    db_session.commit()
    assert client.post(f"/conversations/{w.conv.id}/take-over").status_code == 200


@skip_if_no_db
def test_conversation_payloads_flag_managed_by_saas(client, db_session, as_admin):
    on = _world(db_session, "whatsapp")
    off = _world(db_session, "facebook", connection="conn-off")
    off.channel.saas_delegation_enabled = False
    db_session.commit()
    assert client.get(f"/conversations/{on.conv.id}").json()["managed_by_saas"] is True
    assert client.get(f"/conversations/{off.conv.id}").json()["managed_by_saas"] is False
    listed = {c["id"]: c["managed_by_saas"] for c in client.get("/conversations").json()}
    assert listed[str(on.conv.id)] is True and listed[str(off.conv.id)] is False


# --- Many's AI gates do not apply to a delegated channel -------------------------


def _events(db, channel):
    db.expire_all()
    return db.query(SaasForwardEvent).filter_by(channel_id=channel.id).order_by(SaasForwardEvent.seq).all()


@skip_if_no_db
def test_whatsapp_gates_do_not_apply(db_session):
    acc = _wa_account(db_session, delegated=True, ai_enabled=True)
    first = _run(db_session, wa_payload(acc, "16315551234", "one", "wamid.g1"), "whatsapp_business_account")
    conv = db_session.query(Conversation).filter_by(whatsapp_account_id=acc.id).one()
    conv.status, conv.handoff_reason, conv.turn_count = "handed_off", "turn_limit", 999
    acc.ai_daily_message_cap, acc.ai_messages_sent_today = 1, 1000
    acc.ai_handoff_after_turns = 1
    db_session.commit()
    second = _run(db_session, wa_payload(acc, "16315551234", "two", "wamid.g2"), "whatsapp_business_account")
    assert not first.ai_touched and not second.ai_touched
    assert [e.event_id for e in _events(db_session, acc)] == ["in:whatsapp:wamid.g1", "in:whatsapp:wamid.g2"]
    db_session.refresh(conv)
    assert conv.status == "handed_off" and conv.turn_count == 999  # Many never touches the thread's state


@skip_if_no_db
def test_facebook_gates_do_not_apply(db_session):
    page = _fb_page(db_session, delegated=True, ai_enabled=True)
    _run(db_session, fb_payload(page.page_id, "psid-1", "one", "mid.g1"), "page")
    conv = db_session.query(Conversation).filter_by(facebook_page_id=page.id).one()
    conv.status, conv.turn_count = "handed_off", 999
    page.ai_daily_message_cap, page.ai_messages_sent_today, page.ai_handoff_after_turns = 1, 1000, 1
    db_session.commit()
    second = _run(db_session, fb_payload(page.page_id, "psid-1", "two", "mid.g2"), "page")
    assert not second.ai_touched
    assert [e.event_id for e in _events(db_session, page)] == ["in:facebook:mid.g1", "in:facebook:mid.g2"]


@skip_if_no_db
def test_instagram_gates_do_not_apply_including_inactive_campaign(db_session):
    from app.workers import tasks

    acc = _ig_account(db_session, delegated=True, ai_enabled=True, cold=True)
    campaign = Campaign(id=uuid4(), workspace_id=acc.workspace_id, instagram_account_id=acc.id,
                        name="Old promo", status="paused", ai_enabled=False)
    db_session.add(campaign)
    lead = Lead(id=uuid4(), workspace_id=acc.workspace_id, instagram_account_id=acc.id,
                ig_user_id="9000020", lead_source="campaign", source_campaign_id=campaign.id, status="new")
    db_session.add(lead)
    db_session.commit()
    conv = conversation_service.get_or_create_conversation(
        db_session, workspace_id=acc.workspace_id, lead_id=lead.id,
        campaign_id=campaign.id, instagram_account_id=acc.id,
    )
    conv.status, conv.turn_count = "handed_off", 999
    acc.ai_daily_message_cap, acc.ai_messages_sent_today, acc.ai_handoff_after_turns = 1, 1000, 1
    db_session.commit()
    with patch.object(tasks, "process_ai_conversation_turn") as ig_turn:
        result = _run(db_session, ig_payload(acc.ig_user_id, "9000020", "still there?", "mid.g3"), "instagram")
        assert not ig_turn.delay.called
    assert not result.ai_touched
    [event] = _events(db_session, acc)
    assert event.event_id == "in:instagram:mid.g3" and event.ordering_key == str(conv.id)
