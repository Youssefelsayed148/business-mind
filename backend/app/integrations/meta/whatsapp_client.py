import logging
from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.integrations.meta.errors import classify_meta_error
from app.integrations.meta.messaging import MetaMessageResult
from app.integrations.meta.whatsapp_ids import mask_wa_id

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WhatsappMessageResult:
    """WhatsApp-specific metadata around the shared messaging result."""

    message_result: MetaMessageResult
    meta_error_code: int | None = None
    meta_error_subcode: int | None = None

    @property
    def success(self) -> bool:
        return self.message_result.success

    @property
    def provider_message_id(self) -> str | None:
        return self.message_result.provider_message_id

    @property
    def raw_response(self) -> dict:
        return self.message_result.raw_response

    @property
    def error_code(self) -> str | None:
        return self.message_result.error_code

    @property
    def error_message(self) -> str | None:
        return self.message_result.error_message

    @property
    def retryable(self) -> bool:
        return self.message_result.retryable


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


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
                    "recipient_wa_id": mask_wa_id(recipient_wa_id),
                    "status_code": response.status_code,
                    "error_code": error.get("code"),
                    "error_message": error_msg,
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

    def send_template_message(
        self,
        access_token: str,
        phone_number_id: str,
        to: str,
        template_name: str,
        language: str,
        components: list[dict],
    ) -> WhatsappMessageResult:
        """Send an approved WhatsApp template without exposing recipient data in logs."""
        if settings.META_MOCK_PRIVATE_REPLIES:
            result = MetaMessageResult(
                success=True,
                provider_message_id="mock_wa_template_message",
                raw_response={"messages": [{"id": "mock_wa_template_message"}]},
            )
            return WhatsappMessageResult(message_result=result)

        url = f"{self.base_url}/{phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {access_token}"}
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language},
                "components": components,
            },
        }

        try:
            response = self._client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException:
            logger.warning(
                "WhatsApp template send timeout",
                extra={"recipient_wa_id": mask_wa_id(to)},
            )
            # A timed-out request may already have reached Meta and been
            # delivered, so retrying here could send the template twice.
            result = MetaMessageResult(
                success=False,
                error_code="timeout",
                error_message="Request timed out; delivery outcome unknown",
                retryable=False,
            )
            return WhatsappMessageResult(message_result=result)
        except httpx.HTTPError as exc:
            logger.warning(
                "WhatsApp template send HTTP client error",
                extra={"recipient_wa_id": mask_wa_id(to), "error_type": type(exc).__name__},
            )
            error_code = "network_error" if isinstance(exc, httpx.NetworkError) else "http_error"
            result = MetaMessageResult(
                success=False,
                error_code=error_code,
                error_message="WhatsApp HTTP client error",
            )
            return WhatsappMessageResult(message_result=result)

        try:
            data = response.json()
        except Exception:
            result = MetaMessageResult(
                success=False,
                error_code="invalid_json",
                error_message=f"Invalid JSON response (HTTP {response.status_code})",
                raw_response={"status_code": response.status_code},
            )
            return WhatsappMessageResult(message_result=result)

        if not isinstance(data, dict):
            result = MetaMessageResult(
                success=False,
                error_code="invalid_response",
                error_message=f"Unexpected response shape (HTTP {response.status_code})",
                raw_response={"status_code": response.status_code},
            )
            return WhatsappMessageResult(message_result=result)

        if response.status_code >= 400 or "error" in data:
            classification = classify_meta_error(response.status_code, data)
            error = data.get("error") if isinstance(data.get("error"), dict) else {}
            meta_error_code = _optional_int(error.get("code"))
            meta_error_subcode = _optional_int(error.get("error_subcode"))
            error_message = error.get("message", "WhatsApp Cloud API error")
            logger.error(
                "WhatsApp send_template_message API error",
                extra={
                    "recipient_wa_id": mask_wa_id(to),
                    "status_code": response.status_code,
                    "meta_error_code": meta_error_code,
                    "meta_error_subcode": meta_error_subcode,
                },
            )
            result = MetaMessageResult(
                success=False,
                error_code=classification.category,
                error_message=error_message,
                raw_response=data,
                retryable=classification.retryable,
            )
            return WhatsappMessageResult(
                message_result=result,
                meta_error_code=meta_error_code,
                meta_error_subcode=meta_error_subcode,
            )

        messages = data.get("messages") if isinstance(data.get("messages"), list) else []
        first_message = messages[0] if messages and isinstance(messages[0], dict) else {}
        result = MetaMessageResult(
            success=True,
            provider_message_id=first_message.get("id"),
            raw_response=data,
        )
        return WhatsappMessageResult(message_result=result)

    def close(self) -> None:
        self._client.close()
