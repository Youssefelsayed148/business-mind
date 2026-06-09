import logging

import httpx

from app.core.config import settings
from app.integrations.meta.errors import MetaAPIError, classify_meta_error

logger = logging.getLogger(__name__)


class MetaMessageResult:
    def __init__(
        self,
        success: bool,
        provider_message_id: str | None = None,
        raw_response: dict | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ):
        self.success = success
        self.provider_message_id = provider_message_id
        self.raw_response = raw_response or {}
        self.error_code = error_code
        self.error_message = error_message


class MetaMessagingClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or f"https://graph.facebook.com/{settings.META_GRAPH_API_VERSION}"
        self._client = httpx.AsyncClient(timeout=30.0)

    async def send_private_reply(
        self,
        access_token: str,
        comment_id: str,
        text: str,
    ) -> MetaMessageResult:
        """Send a private reply to an Instagram comment.

        Uses the official Meta Graph API private_replies endpoint.
        Endpoint pattern: POST /{comment_id}/private_replies
        """
        if settings.META_MOCK_PRIVATE_REPLIES:
            return MetaMessageResult(
                success=True,
                provider_message_id=f"mock_message_{comment_id}",
                raw_response={"recipient_id": "mock", "message_id": f"mock_message_{comment_id}"},
            )

        path = f"/{comment_id}/private_replies"
        url = f"{self.base_url}{path}"
        payload = {"message": text}
        params = {"access_token": access_token}

        try:
            response = await self._client.post(url, params=params, json=payload)
        except httpx.NetworkError as exc:
            logger.warning("Meta messaging network error", extra={"error": str(exc)})
            return MetaMessageResult(
                success=False,
                error_code="network_error",
                error_message=str(exc),
            )
        except httpx.TimeoutException as exc:
            logger.warning("Meta messaging timeout", extra={"error": str(exc)})
            return MetaMessageResult(
                success=False,
                error_code="timeout",
                error_message="Request timed out",
            )

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
            return MetaMessageResult(
                success=False,
                error_code=classification.category,
                error_message=error.get("message", "Meta API error"),
                raw_response=data,
            )

        message_id = data.get("id") or data.get("message_id")
        return MetaMessageResult(
            success=True,
            provider_message_id=message_id,
            raw_response=data,
        )

    async def send_follow_prompt_card(
        self,
        access_token: str,
        recipient_id: str,
        title: str,
        description: str,
        profile_url: str,
    ) -> MetaMessageResult:
        """Send a generic template card with a fixed Follow URL button.

        This opens the profile URL only; it does not follow or verify follow state.
        """
        if settings.META_MOCK_PRIVATE_REPLIES:
            return MetaMessageResult(
                success=True,
                provider_message_id=f"mock_follow_prompt_{recipient_id}",
                raw_response={"recipient_id": "mock", "message_id": f"mock_follow_prompt_{recipient_id}"},
            )

        path = f"/{recipient_id}/private_replies"
        url = f"{self.base_url}{path}"
        payload = {
            "message": {
                "attachment": {
                    "type": "template",
                    "payload": {
                        "template_type": "generic",
                        "elements": [
                            {
                                "title": title,
                                "subtitle": description,
                                "buttons": [
                                    {
                                        "type": "web_url",
                                        "title": "Follow",
                                        "url": profile_url,
                                    }
                                ],
                            }
                        ],
                    },
                }
            }
        }
        params = {"access_token": access_token}

        try:
            response = await self._client.post(url, params=params, json=payload)
        except httpx.NetworkError as exc:
            logger.warning("Meta follow prompt network error", extra={"error": str(exc)})
            return MetaMessageResult(success=False, error_code="network_error", error_message=str(exc))
        except httpx.TimeoutException as exc:
            logger.warning("Meta follow prompt timeout", extra={"error": str(exc)})
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
            return MetaMessageResult(
                success=False,
                error_code=classification.category,
                error_message=error.get("message", "Meta API error"),
                raw_response=data,
            )

        message_id = data.get("id") or data.get("message_id")
        return MetaMessageResult(success=True, provider_message_id=message_id, raw_response=data)

    async def close(self):
        await self._client.aclose()
