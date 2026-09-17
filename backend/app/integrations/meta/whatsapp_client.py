import logging

import httpx

from app.core.config import settings
from app.integrations.meta.errors import classify_meta_error
from app.integrations.meta.messaging import MetaMessageResult

logger = logging.getLogger(__name__)


class WhatsappClient:
    """Synchronous WhatsApp Cloud API client for use inside Celery tasks.

    Not a subclass of MetaMessagingClient — that client is hardcoded to
    graph.instagram.com and Instagram's recipient-object message shape.
    WhatsApp Cloud API lives on graph.facebook.com, authenticates via a
    Bearer header (not an access_token query param), and has its own
    message envelope (`messaging_product`/`to`/`type`).

    Reuses MetaMessageResult (a plain value object with no IG-specific
    fields) and classify_meta_error (a generic Graph API error-shape
    classifier) since both are already platform-agnostic.
    """

    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or f"https://graph.facebook.com/{settings.META_GRAPH_API_VERSION}"
        self._client = httpx.Client(timeout=30.0)

    def send_text_message(
        self,
        access_token: str,
        phone_number_id: str,
        recipient_wa_id: str,
        text: str,
    ) -> MetaMessageResult:
        """Send a plain text message to an open 24-hour conversation window.

        Endpoint: POST /{phone_number_id}/messages
        """
        if settings.META_MOCK_PRIVATE_REPLIES:
            return MetaMessageResult(
                success=True,
                provider_message_id=f"mock_wa_{recipient_wa_id}",
                raw_response={"recipient_wa_id": recipient_wa_id, "message_id": f"mock_wa_{recipient_wa_id}"},
            )

        url = f"{self.base_url}/{phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {access_token}"}
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient_wa_id,
            "type": "text",
            "text": {"body": text},
        }

        try:
            response = self._client.post(url, headers=headers, json=payload)
        except httpx.NetworkError as exc:
            logger.warning("WhatsApp messaging network error", extra={"error": str(exc)})
            return MetaMessageResult(success=False, error_code="network_error", error_message=str(exc))
        except httpx.TimeoutException as exc:
            logger.warning("WhatsApp messaging timeout", extra={"error": str(exc)})
            return MetaMessageResult(success=False, error_code="timeout", error_message="Request timed out")

        try:
            data = response.json()
        except Exception:
            return MetaMessageResult(
                success=False,
                error_code="invalid_json",
                error_message=f"Invalid JSON response (HTTP {response.status_code})",
                raw_response={"status_code": response.status_code, "text": response.text},
            )

        if response.status_code >= 400 or "error" in data:
            classification = classify_meta_error(response.status_code, data)
            error = data.get("error", {})
            error_msg = error.get("message", "WhatsApp Cloud API error")
            logger.error(
                "WhatsApp send_text_message API error",
                extra={
                    "recipient_wa_id": recipient_wa_id,
                    "status_code": response.status_code,
                    "error_code": error.get("code"),
                    "error_message": error_msg,
                    "raw_response": data,
                },
            )
            return MetaMessageResult(
                success=False,
                error_code=classification.category,
                error_message=error_msg,
                raw_response=data,
                retryable=classification.retryable,
            )

        messages = data.get("messages", [])
        message_id = messages[0].get("id") if messages else None
        return MetaMessageResult(success=True, provider_message_id=message_id, raw_response=data)

    def close(self) -> None:
        self._client.close()
