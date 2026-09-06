"""Every platform's successful webhook run must leave a `webhook_processed`
audit row.

Only the Instagram branch reached that log call -- the WhatsApp and Facebook
branches return before it -- so a successful WA/FB webhook was invisible in the
dashboard's log view. The `platform` detail makes the three distinguishable.
"""

from unittest.mock import patch
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.automation_log import AutomationLog
from app.models.facebook_page import FacebookPage
from app.models.processed_webhook_event import ProcessedWebhookEvent  # noqa: F401 (register table)
from app.models.webhook_event import WebhookEvent
from app.models.whatsapp_account import WhatsappAccount
from app.models.workspace import Workspace
from tests.conftest import skip_if_no_db


def _run(db: Session, payload: dict, *, mock_name: str) -> WebhookEvent:
    from app.workers import tasks

    event = WebhookEvent(
        provider="meta",
        external_event_id=uuid4().hex,
        event_type=payload["object"],
        payload=payload,
        processing_status="pending",
    )
    db.add(event)
    db.commit()

    orig_close = db.close
    db.close = lambda: None
    try:
        with patch.object(tasks, "_get_db", return_value=db), patch.object(tasks, mock_name):
            tasks.process_webhook_event(str(event.id))
    finally:
        db.close = orig_close

    db.refresh(event)
    return event


def _processed_logs(db: Session, event: WebhookEvent) -> list[AutomationLog]:
    return [
        row
        for row in db.query(AutomationLog).filter(AutomationLog.action == "webhook_processed").all()
        if (row.details or {}).get("event_id") == str(event.id)
    ]


@skip_if_no_db
def test_whatsapp_success_is_logged(db_session: Session):
    ws = Workspace(id=uuid4(), name="Default", slug=f"log-wa-{uuid4().hex[:8]}")
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

    event = _run(
        db_session,
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "waba_1",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "metadata": {"phone_number_id": account.phone_number_id},
                                "contacts": [{"wa_id": "20100000111", "profile": {"name": "X"}}],
                                "messages": [
                                    {
                                        "from": "20100000111",
                                        "id": "wamid.log.1",
                                        "type": "text",
                                        "text": {"body": "hi"},
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        },
        mock_name="process_whatsapp_ai_conversation_turn",
    )

    assert event.processing_status == "processed"
    logs = _processed_logs(db_session, event)
    assert len(logs) == 1
    assert logs[0].details["platform"] == "whatsapp"


@skip_if_no_db
def test_facebook_success_is_logged(db_session: Session):
    ws = Workspace(id=uuid4(), name="Default", slug=f"log-fb-{uuid4().hex[:8]}")
    db_session.add(ws)
    db_session.commit()
    page = FacebookPage(
        id=uuid4(),
        workspace_id=ws.id,
        page_id=f"page_{uuid4().int % 10_000_000}",
        status="connected",
        ai_enabled=True,
        ai_cold_dm_enabled=True,
        ai_daily_message_cap=100,
    )
    db_session.add(page)
    db_session.commit()

    event = _run(
        db_session,
        {
            "object": "page",
            "entry": [
                {
                    "id": page.page_id,
                    "messaging": [
                        {
                            "sender": {"id": "psid_log_1"},
                            "recipient": {"id": page.page_id},
                            "timestamp": 1700000000,
                            "message": {"mid": "mid.log.1", "text": "hi"},
                        }
                    ],
                }
            ],
        },
        mock_name="process_facebook_ai_conversation_turn",
    )

    assert event.processing_status == "processed"
    logs = _processed_logs(db_session, event)
    assert len(logs) == 1
    assert logs[0].details["platform"] == "facebook"
