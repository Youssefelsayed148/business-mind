from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.models.campaign import Campaign
from app.models.comment import Comment
from app.models.instagram_account import InstagramAccount
from app.models.lead import Lead
from app.models.message import Message
from app.models.meta_token import MetaToken
from app.models.workspace import Workspace
from app.services.token_service import store_encrypted_token
from app.workers.tasks import send_private_reply
from tests.conftest import skip_if_no_db


@pytest.fixture(autouse=True)
def worker_uses_fixture_transaction(db_session, monkeypatch):
    from app.workers import tasks

    # Use the fixture session so a later duplicate rollback cannot undo a
    # worker commit made inside the request session's still-open savepoint.
    monkeypatch.setattr(tasks, "_get_db", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)


@skip_if_no_db
def test_send_private_reply_success(db_session: Session):
    ws = Workspace(id=uuid4(), name="Default", slug="default")
    db_session.add(ws)
    db_session.commit()

    acc = InstagramAccount(
        workspace_id=ws.id,
        ig_user_id="ig_send",
        ig_username="sendacc",
    )
    db_session.add(acc)
    db_session.commit()

    store_encrypted_token(db_session, ws.id, acc.id, "fake_token")

    campaign = Campaign(
        id=uuid4(),
        workspace_id=ws.id,
        instagram_account_id=acc.id,
        name="Send",
        media_id="m1",
        message_template="Hi",
        match_type="contains",
        status="active",
    )
    db_session.add(campaign)
    db_session.commit()

    lead = Lead(
        id=uuid4(),
        workspace_id=ws.id,
        instagram_account_id=acc.id,
        ig_user_id="u1",
    )
    db_session.add(lead)
    db_session.commit()

    comment = Comment(
        id=uuid4(),
        instagram_account_id=acc.id,
        comment_id="c_send",
        ig_user_id="u1",
    )
    db_session.add(comment)
    db_session.commit()

    msg = Message(
        id=uuid4(),
        campaign_id=campaign.id,
        lead_id=lead.id,
        comment_id=comment.id,
        status="queued",
        rendered_body="Hello there",
    )
    db_session.add(msg)
    db_session.commit()

    mock_result = MagicMock()
    mock_result.success = True
    mock_result.provider_message_id = "pm_123"
    mock_result.error_code = None
    mock_result.error_message = None
    mock_result.retryable = False

    with patch(
        "app.workers.tasks.MetaMessagingClient.send_private_reply",
        new_callable=MagicMock,
        return_value=mock_result,
    ), patch("app.workers.tasks.MetaMessagingClient.close", new_callable=MagicMock):
        send_private_reply(str(msg.id))

    db_session.refresh(msg)
    assert msg.status == "sent"
    assert msg.provider_message_id == "pm_123"


@skip_if_no_db
def test_send_private_reply_expired_private_reply(db_session: Session):
    ws = Workspace(id=uuid4(), name="Default", slug="default")
    db_session.add(ws)
    db_session.commit()

    acc = InstagramAccount(
        workspace_id=ws.id,
        ig_user_id="ig_exp",
        ig_username="expacc",
    )
    db_session.add(acc)
    db_session.commit()

    store_encrypted_token(db_session, ws.id, acc.id, "fake_token")

    campaign = Campaign(
        id=uuid4(),
        workspace_id=ws.id,
        instagram_account_id=acc.id,
        name="Exp",
        media_id="m1",
        message_template="Hi",
        match_type="contains",
        status="active",
    )
    db_session.add(campaign)
    db_session.commit()

    lead = Lead(
        id=uuid4(),
        workspace_id=ws.id,
        instagram_account_id=acc.id,
        ig_user_id="u1",
    )
    db_session.add(lead)
    db_session.commit()

    comment = Comment(
        id=uuid4(),
        instagram_account_id=acc.id,
        comment_id="c_exp",
        ig_user_id="u1",
    )
    db_session.add(comment)
    db_session.commit()

    msg = Message(
        id=uuid4(),
        campaign_id=campaign.id,
        lead_id=lead.id,
        comment_id=comment.id,
        status="queued",
        rendered_body="Hello",
    )
    db_session.add(msg)
    db_session.commit()

    mock_result = MagicMock()
    mock_result.success = False
    mock_result.error_code = "expired_private_reply"
    mock_result.error_message = "Private reply window expired"
    mock_result.retryable = False

    with patch(
        "app.workers.tasks.MetaMessagingClient.send_private_reply",
        new_callable=MagicMock,
        return_value=mock_result,
    ), patch("app.workers.tasks.MetaMessagingClient.close", new_callable=MagicMock):
        send_private_reply(str(msg.id))

    db_session.refresh(msg)
    assert msg.status == "expired"
    assert msg.error_code == "expired_private_reply"


@skip_if_no_db
def test_send_private_reply_token_error_no_retry(db_session: Session):
    ws = Workspace(id=uuid4(), name="Default", slug="default")
    db_session.add(ws)
    db_session.commit()

    acc = InstagramAccount(
        workspace_id=ws.id,
        ig_user_id="ig_tok",
        ig_username="tokacc",
    )
    db_session.add(acc)
    db_session.commit()

    store_encrypted_token(db_session, ws.id, acc.id, "fake_token")

    campaign = Campaign(
        id=uuid4(),
        workspace_id=ws.id,
        instagram_account_id=acc.id,
        name="Tok",
        media_id="m1",
        message_template="Hi",
        match_type="contains",
        status="active",
    )
    db_session.add(campaign)
    db_session.commit()

    lead = Lead(
        id=uuid4(),
        workspace_id=ws.id,
        instagram_account_id=acc.id,
        ig_user_id="u1",
    )
    db_session.add(lead)
    db_session.commit()

    comment = Comment(
        id=uuid4(),
        instagram_account_id=acc.id,
        comment_id="c_tok",
        ig_user_id="u1",
    )
    db_session.add(comment)
    db_session.commit()

    msg = Message(
        id=uuid4(),
        campaign_id=campaign.id,
        lead_id=lead.id,
        comment_id=comment.id,
        status="queued",
        rendered_body="Hello",
    )
    db_session.add(msg)
    db_session.commit()

    mock_result = MagicMock()
    mock_result.success = False
    mock_result.error_code = "token_error"
    mock_result.error_message = "Invalid access token"
    mock_result.retryable = False

    with patch(
        "app.workers.tasks.MetaMessagingClient.send_private_reply",
        new_callable=MagicMock,
        return_value=mock_result,
    ), patch("app.workers.tasks.MetaMessagingClient.close", new_callable=MagicMock):
        send_private_reply(str(msg.id))

    db_session.refresh(msg)
    assert msg.status == "failed"
    assert msg.error_code == "token_error"
    assert msg.retryable is False


@skip_if_no_db
def test_send_private_reply_retryable_500(db_session: Session):
    ws = Workspace(id=uuid4(), name="Default", slug="default")
    db_session.add(ws)
    db_session.commit()

    acc = InstagramAccount(
        workspace_id=ws.id,
        ig_user_id="ig_retry",
        ig_username="retryacc",
    )
    db_session.add(acc)
    db_session.commit()

    store_encrypted_token(db_session, ws.id, acc.id, "fake_token")

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

    lead = Lead(
        id=uuid4(),
        workspace_id=ws.id,
        instagram_account_id=acc.id,
        ig_user_id="u1",
    )
    db_session.add(lead)
    db_session.commit()

    comment = Comment(
        id=uuid4(),
        instagram_account_id=acc.id,
        comment_id="c_retry",
        ig_user_id="u1",
    )
    db_session.add(comment)
    db_session.commit()

    msg = Message(
        id=uuid4(),
        campaign_id=campaign.id,
        lead_id=lead.id,
        comment_id=comment.id,
        status="queued",
        rendered_body="Hello",
    )
    db_session.add(msg)
    db_session.commit()

    mock_result = MagicMock()
    mock_result.success = False
    mock_result.error_code = "retryable"
    mock_result.error_message = "Internal server error"
    mock_result.retryable = True

    from celery.exceptions import Retry

    with patch(
        "app.workers.tasks.MetaMessagingClient.send_private_reply",
        new_callable=MagicMock,
        return_value=mock_result,
    ), patch("app.workers.tasks.MetaMessagingClient.close", new_callable=MagicMock), patch.object(
        send_private_reply, "retry", side_effect=Retry()
    ) as retry_task:
        with pytest.raises(Retry):
            send_private_reply(str(msg.id))
        assert retry_task.call_count == 1
        assert retry_task.call_args.kwargs["countdown"] == 60

    db_session.refresh(msg)
    assert msg.status == "failed"
    assert msg.retryable is True
