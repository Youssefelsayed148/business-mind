"""`get_or_create_conversation` must not create two conversations for one lead.

The two existing unique constraints on `conversations` are plain UNIQUE
constraints on (lead_id, campaign_id) and (lead_id, facebook_campaign_id), and
Postgres treats NULL as distinct from every other NULL in one -- so neither
constrains anything for a NULL-campaign conversation. Every WhatsApp
conversation and every cold-DM conversation is NULL-campaign, so before the
partial index `uq_conversation_lead_cold_dm` there was nothing at all stopping
two concurrent workers from creating two conversations for the same lead.

These tests drive the real database, so the constraint and the
ON CONFLICT DO NOTHING path are both genuinely exercised rather than mocked.
"""

from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.campaign import Campaign
from app.models.conversation import Conversation
from app.models.facebook_campaign import FacebookCampaign
from app.models.facebook_page import FacebookPage
from app.models.instagram_account import InstagramAccount
from app.models.lead import Lead
from app.models.whatsapp_account import WhatsappAccount
from app.models.workspace import Workspace
from app.services import conversation_service
from tests.conftest import skip_if_no_db


def _workspace(db: Session) -> Workspace:
    ws = Workspace(id=uuid4(), name="Default", slug=f"conv-{uuid4().hex[:8]}")
    db.add(ws)
    db.commit()
    return ws


def _whatsapp_lead(db: Session):
    ws = _workspace(db)
    account = WhatsappAccount(
        id=uuid4(),
        workspace_id=ws.id,
        phone_number_id=f"pn_{uuid4().int % 10_000_000}",
        ai_daily_message_cap=100,
    )
    db.add(account)
    db.commit()
    lead = Lead(
        id=uuid4(),
        workspace_id=ws.id,
        platform="whatsapp",
        whatsapp_account_id=account.id,
        ig_user_id="20100000000",
        lead_source="cold_dm",
        status="new",
    )
    db.add(lead)
    db.commit()
    return ws, account, lead


@skip_if_no_db
def test_second_call_returns_the_same_whatsapp_conversation(db_session: Session):
    ws, account, lead = _whatsapp_lead(db_session)

    first = conversation_service.get_or_create_conversation(
        db_session,
        workspace_id=ws.id,
        lead_id=lead.id,
        campaign_id=None,
        platform="whatsapp",
        whatsapp_account_id=account.id,
    )
    second = conversation_service.get_or_create_conversation(
        db_session,
        workspace_id=ws.id,
        lead_id=lead.id,
        campaign_id=None,
        platform="whatsapp",
        whatsapp_account_id=account.id,
    )

    assert first.id == second.id
    assert db_session.query(Conversation).filter(Conversation.lead_id == lead.id).count() == 1


@skip_if_no_db
def test_partial_index_rejects_a_second_null_campaign_conversation(db_session: Session):
    """The database itself refuses the duplicate -- this is what makes the
    concurrent case safe, not just the read-then-insert ordering."""
    ws, account, lead = _whatsapp_lead(db_session)
    conversation_service.get_or_create_conversation(
        db_session,
        workspace_id=ws.id,
        lead_id=lead.id,
        campaign_id=None,
        platform="whatsapp",
        whatsapp_account_id=account.id,
    )

    # Bypass the service entirely: this is exactly the row a racing worker
    # would have inserted before the partial index existed.
    db_session.add(
        Conversation(
            id=uuid4(),
            workspace_id=ws.id,
            lead_id=lead.id,
            campaign_id=None,
            platform="whatsapp",
            whatsapp_account_id=account.id,
            status="bot_active",
            turn_count=0,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


@skip_if_no_db
def test_lost_race_reaches_the_on_conflict_arm_and_returns_the_winner(db_session: Session):
    """Genuinely stage the race: the winning row must appear *after* this
    call's own lookup has already run and missed it.

    An earlier version of this test pre-inserted the winner before calling the
    service, which meant the service's initial lookup found it and returned
    immediately -- the ON CONFLICT recovery arm was never reached (verified:
    zero ON CONFLICT statements issued), so the test would have kept passing
    with that logic deleted entirely. The insert is now injected into the real
    window, mirroring test_lead_creation_race.py's staged-race pattern.
    """
    ws, account, lead = _whatsapp_lead(db_session)

    winner_id = uuid4()
    seen = {"on_conflict": 0}
    real_execute = type(db_session).execute

    def staged_execute(self, statement, *args, **kwargs):
        if "ON CONFLICT" in str(statement).upper():
            seen["on_conflict"] += 1
            if seen["on_conflict"] == 1:
                # The other worker commits its row here -- after our lookup
                # missed, before our insert lands.
                self.add(
                    Conversation(
                        id=winner_id,
                        workspace_id=ws.id,
                        lead_id=lead.id,
                        campaign_id=None,
                        platform="whatsapp",
                        whatsapp_account_id=account.id,
                        status="bot_active",
                        turn_count=0,
                    )
                )
                self.flush()
        return real_execute(self, statement, *args, **kwargs)

    with patch.object(type(db_session), "execute", staged_execute):
        got = conversation_service.get_or_create_conversation(
            db_session,
            workspace_id=ws.id,
            lead_id=lead.id,
            campaign_id=None,
            platform="whatsapp",
            whatsapp_account_id=account.id,
        )

    assert seen["on_conflict"] >= 1, "the ON CONFLICT arm was never exercised"
    assert got.id == winner_id, "must return the winner's row, not raise or duplicate"
    assert db_session.query(Conversation).filter(Conversation.lead_id == lead.id).count() == 1


@skip_if_no_db
def test_instagram_campaign_conversations_are_unaffected(db_session: Session):
    """The partial index excludes campaign-backed rows, so Instagram's
    existing behaviour -- one conversation per (lead, campaign), and a
    separate cold-DM one -- must still hold."""
    ws = _workspace(db_session)
    account = InstagramAccount(
        id=uuid4(),
        workspace_id=ws.id,
        ig_user_id=f"ig_{uuid4().int % 10_000_000}",
        ig_username="acct",
        ai_daily_message_cap=100,
    )
    db_session.add(account)
    db_session.commit()

    campaigns = []
    for name in ("A", "B"):
        campaign = Campaign(
            id=uuid4(),
            workspace_id=ws.id,
            instagram_account_id=account.id,
            name=name,
            message_template="hi",
            status="active",
        )
        db_session.add(campaign)
        campaigns.append(campaign)
    db_session.commit()

    lead = Lead(
        id=uuid4(),
        workspace_id=ws.id,
        platform="instagram",
        instagram_account_id=account.id,
        ig_user_id="igsid_1",
        lead_source="campaign",
        status="new",
    )
    db_session.add(lead)
    db_session.commit()

    a = conversation_service.get_or_create_conversation(
        db_session, ws.id, lead.id, campaigns[0].id, account.id
    )
    b = conversation_service.get_or_create_conversation(
        db_session, ws.id, lead.id, campaigns[1].id, account.id
    )
    cold = conversation_service.get_or_create_conversation(
        db_session, ws.id, lead.id, None, account.id
    )

    assert len({a.id, b.id, cold.id}) == 3, "two campaigns plus a cold DM are three threads"
    # And the campaign calls are still idempotent.
    assert conversation_service.get_or_create_conversation(
        db_session, ws.id, lead.id, campaigns[0].id, account.id
    ).id == a.id


@skip_if_no_db
def test_facebook_campaign_and_cold_dm_conversations_stay_separate(db_session: Session):
    ws = _workspace(db_session)
    page = FacebookPage(
        id=uuid4(),
        workspace_id=ws.id,
        page_id=f"page_{uuid4().int % 10_000_000}",
        ai_daily_message_cap=100,
    )
    db_session.add(page)
    db_session.commit()
    campaign = FacebookCampaign(
        id=uuid4(),
        workspace_id=ws.id,
        facebook_page_id=page.id,
        name="Promo",
        message_template="hi",
        status="active",
    )
    db_session.add(campaign)
    lead = Lead(
        id=uuid4(),
        workspace_id=ws.id,
        platform="facebook",
        facebook_page_id=page.id,
        ig_user_id="asid_1",
        lead_source="campaign",
        status="new",
    )
    db_session.add(lead)
    db_session.commit()

    campaign_conv = conversation_service.get_or_create_conversation(
        db_session,
        workspace_id=ws.id,
        lead_id=lead.id,
        campaign_id=None,
        platform="facebook",
        facebook_page_id=page.id,
        facebook_campaign_id=campaign.id,
    )
    cold_conv = conversation_service.get_or_create_conversation(
        db_session,
        workspace_id=ws.id,
        lead_id=lead.id,
        campaign_id=None,
        platform="facebook",
        facebook_page_id=page.id,
        facebook_campaign_id=None,
    )

    assert campaign_conv.id != cold_conv.id, (
        "a Facebook cold-DM lookup must not return the campaign conversation"
    )
    assert campaign_conv.facebook_campaign_id == campaign.id
    assert cold_conv.facebook_campaign_id is None


# --- Real concurrency -------------------------------------------------------
#
# Everything above runs in one session inside the harness's rollback-wrapped
# transaction, which proves idempotence but cannot prove race-safety: a single
# session can never actually race itself. The test below uses two threads on
# two real connections, barrier-synchronised so both are past their lookup
# before either inserts. It therefore manages its own engine and committed
# data, and cleans up after itself, rather than using the `db_session` fixture.


@skip_if_no_db
def test_concurrent_callers_get_one_conversation(request):
    """Two workers, two connections, both racing for the same lead.

    Without `uq_conversation_lead_cold_dm` this reliably produces two
    conversation rows (verified: 6/6 runs duplicated with the index dropped).
    With it, the loser's ON CONFLICT DO NOTHING inserts nothing and re-reads
    the winner.
    """
    import threading

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.config import settings

    engine = create_engine(settings.DATABASE_URL)
    Session_ = sessionmaker(bind=engine)

    setup = Session_()
    ws = Workspace(id=uuid4(), name="Default", slug=f"race-{uuid4().hex[:8]}")
    setup.add(ws)
    setup.commit()
    account = WhatsappAccount(
        id=uuid4(),
        workspace_id=ws.id,
        phone_number_id=f"pn_{uuid4().int % 10_000_000}",
        ai_daily_message_cap=100,
    )
    setup.add(account)
    setup.commit()
    lead = Lead(
        id=uuid4(),
        workspace_id=ws.id,
        platform="whatsapp",
        whatsapp_account_id=account.id,
        ig_user_id=uuid4().hex,
        lead_source="cold_dm",
        status="new",
    )
    setup.add(lead)
    setup.commit()
    ws_id, account_id, lead_id = ws.id, account.id, lead.id
    setup.close()

    def _cleanup():
        s = Session_()
        try:
            s.query(Conversation).filter(Conversation.lead_id == lead_id).delete(
                synchronize_session=False
            )
            s.query(Lead).filter(Lead.id == lead_id).delete(synchronize_session=False)
            s.query(WhatsappAccount).filter(WhatsappAccount.id == account_id).delete(
                synchronize_session=False
            )
            s.query(Workspace).filter(Workspace.id == ws_id).delete(synchronize_session=False)
            s.commit()
        finally:
            s.close()
            engine.dispose()

    request.addfinalizer(_cleanup)

    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def worker(name: str) -> None:
        db = Session_()
        try:
            # Both threads complete a lookup that misses, then release
            # together -- so both genuinely attempt the insert.
            db.query(Conversation).filter(Conversation.lead_id == lead_id).first()
            barrier.wait(timeout=10)
            conversation = conversation_service.get_or_create_conversation(
                db,
                workspace_id=ws_id,
                lead_id=lead_id,
                campaign_id=None,
                platform="whatsapp",
                whatsapp_account_id=account_id,
            )
            results[name] = conversation.id
        except Exception as exc:  # surfaced as a test failure below
            results[name] = exc
        finally:
            db.close()

    threads = [threading.Thread(target=worker, args=(f"t{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert len(results) == 2, f"a worker never finished: {results}"
    failures = {k: v for k, v in results.items() if isinstance(v, Exception)}
    assert not failures, f"a concurrent caller raised: {failures}"
    assert len(set(results.values())) == 1, (
        f"the two workers got different conversations: {results}"
    )

    check = Session_()
    try:
        assert (
            check.query(Conversation).filter(Conversation.lead_id == lead_id).count() == 1
        ), "the race produced duplicate conversations"
    finally:
        check.close()
