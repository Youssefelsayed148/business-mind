"""Losing a lead-creation race must not lose the customer's message.

`uq_lead_workspace_whatsapp_user` / `uq_lead_workspace_facebook_user` correctly
raise IntegrityError when two workers try to create the same lead at once. Left
uncaught, that unwinds to process_webhook_event's handler and the event is
marked failed -- and since check_and_mark_processed already consumed the dedup
key, Meta's retry of that same webhook is then swallowed and the message is
gone permanently.

The race is staged by committing the "other worker's" row in the window
between our lookup and our insert, so the unique constraint really does fire.
"""

from unittest.mock import patch

import pytest
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.facebook_page import FacebookPage
from app.models.lead import Lead
from app.models.processed_webhook_event import ProcessedWebhookEvent  # noqa: F401 (register table)
from app.models.webhook_event import WebhookEvent
from app.models.whatsapp_account import WhatsappAccount
from app.models.workspace import Workspace
from tests.conftest import skip_if_no_db


@skip_if_no_db
def test_whatsapp_lead_race_does_not_fail_the_event(db_session: Session):
    """Full webhook path: the lead already exists by the time we insert.

    The race is staged by letting the dispatch build its Lead and then having
    the unique constraint reject it -- the same outcome a concurrent worker
    produces. Before the fix this marked the event failed and, with the dedup
    key already consumed, lost the message for good.
    """
    from app.workers import tasks

    ws = Workspace(id=uuid4(), name="Default", slug=f"race-wa-{uuid4().hex[:8]}")
    db_session.add(ws)
    db_session.commit()
    account = WhatsappAccount(
        id=uuid4(),
        workspace_id=ws.id,
        phone_number_id=f"pn_{uuid4().int % 10_000_000}",
        status="connected",
        ai_enabled=True,
        ai_daily_message_cap=100,
    )
    db_session.add(account)
    db_session.commit()

    sender = "20100000099"
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba_1",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": account.phone_number_id},
                            "contacts": [{"wa_id": sender, "profile": {"name": "Racer"}}],
                            "messages": [
                                {
                                    "from": sender,
                                    "id": "wamid.race.1",
                                    "type": "text",
                                    "text": {"body": "hello"},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }

    event = WebhookEvent(
        provider="meta",
        external_event_id=uuid4().hex,
        event_type="whatsapp_business_account",
        payload=payload,
        processing_status="pending",
    )
    db_session.add(event)
    db_session.commit()

    real_helper = tasks._create_lead_or_reuse_concurrent

    def racing_helper(db, lead, lookup):
        # Commit the concurrent worker's row first, so our insert is the one
        # that loses -- precisely the window between SELECT and INSERT.
        if lookup() is None:
            db.add(
                Lead(
                    id=uuid4(),
                    workspace_id=lead.workspace_id,
                    platform=lead.platform,
                    whatsapp_account_id=lead.whatsapp_account_id,
                    ig_user_id=lead.ig_user_id,
                    lead_source="cold_dm",
                    status="new",
                )
            )
            db.commit()
        return real_helper(db, lead, lookup)

    orig_close = db_session.close
    db_session.close = lambda: None
    try:
        with patch.object(tasks, "_get_db", return_value=db_session), patch.object(
            tasks, "process_whatsapp_ai_conversation_turn"
        ) as mock_turn, patch.object(
            tasks, "_create_lead_or_reuse_concurrent", side_effect=racing_helper
        ):
            tasks.process_webhook_event(str(event.id))
    finally:
        db_session.close = orig_close

    db_session.refresh(event)
    assert event.processing_status == "processed", "the event must not be marked failed"
    assert mock_turn.delay.called, "the message must still be answered"
    assert (
        db_session.query(Lead).filter(Lead.whatsapp_account_id == account.id).count() == 1
    ), "no duplicate lead"


@skip_if_no_db
def test_helper_recovers_onto_the_existing_row(db_session: Session):
    """Direct unit coverage of the recovery helper itself."""
    from app.workers.tasks import _create_lead_or_reuse_concurrent

    ws = Workspace(id=uuid4(), name="Default", slug=f"race-h-{uuid4().hex[:8]}")
    db_session.add(ws)
    db_session.commit()
    page = FacebookPage(
        id=uuid4(),
        workspace_id=ws.id,
        page_id=f"page_{uuid4().int % 10_000_000}",
        ai_daily_message_cap=100,
    )
    db_session.add(page)
    db_session.commit()

    def _mk():
        return Lead(
            id=uuid4(),
            workspace_id=ws.id,
            platform="facebook",
            facebook_page_id=page.id,
            ig_user_id="dupe_user",
            lead_source="cold_dm",
            status="new",
        )

    def _lookup():
        return (
            db_session.query(Lead)
            .filter(Lead.facebook_page_id == page.id, Lead.ig_user_id == "dupe_user")
            .first()
        )

    winner = _create_lead_or_reuse_concurrent(db_session, _mk(), _lookup)
    assert winner is not None

    loser = _create_lead_or_reuse_concurrent(db_session, _mk(), _lookup)
    assert loser is not None
    assert loser.id == winner.id, "must recover onto the winner, not raise"
    assert db_session.query(Lead).filter(Lead.facebook_page_id == page.id).count() == 1


@skip_if_no_db
def test_non_unique_integrity_error_is_not_treated_as_a_race(db_session: Session):
    """A CHECK violation is a data bug, not contention.

    IntegrityError also covers CHECK, foreign-key and NOT NULL violations.
    Swallowing those as "someone beat us to it" made the helper return None,
    the caller `continue`, and the customer's message vanish with only a log
    line -- a genuine bug reported as a skipped event. Only SQLSTATE 23505
    (unique_violation) is a race; everything else must surface.
    """
    from sqlalchemy.exc import IntegrityError

    from app.workers.tasks import _create_lead_or_reuse_concurrent

    ws = Workspace(id=uuid4(), name="Default", slug=f"race-chk-{uuid4().hex[:8]}")
    db_session.add(ws)
    db_session.commit()

    # platform='whatsapp' with no whatsapp_account_id violates
    # ck_leads_platform_account_fk -- exactly the shape of a real data bug.
    bad = Lead(
        id=uuid4(),
        workspace_id=ws.id,
        platform="whatsapp",
        whatsapp_account_id=None,
        ig_user_id="check-violation",
        lead_source="cold_dm",
        status="new",
    )

    with pytest.raises(IntegrityError) as excinfo:
        _create_lead_or_reuse_concurrent(db_session, bad, lambda: None)

    assert excinfo.value.orig.sqlstate == "23514", "should be the CHECK violation, re-raised"
    db_session.rollback()


@skip_if_no_db
def test_unique_violation_is_still_recovered(db_session: Session):
    """The narrowed catch must not stop recovering from the real race."""
    from app.workers.tasks import _create_lead_or_reuse_concurrent

    ws = Workspace(id=uuid4(), name="Default", slug=f"race-uq-{uuid4().hex[:8]}")
    db_session.add(ws)
    db_session.commit()
    page = FacebookPage(
        id=uuid4(),
        workspace_id=ws.id,
        page_id=f"page_{uuid4().int % 10_000_000}",
        ai_daily_message_cap=100,
    )
    db_session.add(page)
    db_session.commit()

    def _mk():
        return Lead(
            id=uuid4(),
            workspace_id=ws.id,
            platform="facebook",
            facebook_page_id=page.id,
            ig_user_id="same_user",
            lead_source="cold_dm",
            status="new",
        )

    def _lookup():
        return (
            db_session.query(Lead)
            .filter(Lead.facebook_page_id == page.id, Lead.ig_user_id == "same_user")
            .first()
        )

    winner = _create_lead_or_reuse_concurrent(db_session, _mk(), _lookup)
    loser = _create_lead_or_reuse_concurrent(db_session, _mk(), _lookup)

    assert loser is not None and loser.id == winner.id
    assert db_session.query(Lead).filter(Lead.facebook_page_id == page.id).count() == 1
