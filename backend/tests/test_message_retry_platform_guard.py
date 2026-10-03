import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.routes_messages import retry_message


@pytest.mark.parametrize("whatsapp_campaign_id", [uuid4(), None])
def test_retry_rejects_whatsapp_message(whatsapp_campaign_id):
    message = SimpleNamespace(
        id=uuid4(),
        lead_id=uuid4(),
        campaign_id=None,
        whatsapp_campaign_id=whatsapp_campaign_id,
        message_type="whatsapp_template",
        status="failed",
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.scalar.return_value = "whatsapp"

    with patch("app.api.routes_messages.get_message_for_send", return_value=message):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(retry_message(message.id, db=db, current_user=MagicMock()))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "WhatsApp messages are retried by their campaign"


def test_retry_still_accepts_instagram_message():
    message = SimpleNamespace(
        id=uuid4(),
        lead_id=uuid4(),
        campaign_id=uuid4(),
        whatsapp_campaign_id=None,
        message_type="final_delivery",
        status="failed",
    )
    lead_query = MagicMock()
    lead_query.filter.return_value.scalar.return_value = "instagram"
    campaign_query = MagicMock()
    campaign_query.filter.return_value.first.return_value = None
    db = MagicMock()
    db.query.side_effect = [lead_query, campaign_query]

    with patch("app.api.routes_messages.get_message_for_send", return_value=message), patch(
        "app.workers.tasks.send_private_reply.delay"
    ) as mock_delay:
        result = asyncio.run(
            retry_message(message.id, db=db, current_user=MagicMock())
        )

    assert result == {"status": "retry_enqueued", "message_id": str(message.id)}
    mock_delay.assert_called_once_with(str(message.id))
