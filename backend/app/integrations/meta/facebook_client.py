import logging

import httpx

from app.core.config import settings
from app.integrations.meta.errors import classify_meta_error
from app.integrations.meta.messaging import MetaMessageResult

logger = logging.getLogger(__name__)


class FacebookClient:
    """Synchronous Facebook Page Graph API client for use inside Celery tasks.

    Mirrors MetaMessagingClient's two-send-method split
    (send_private_reply / send_direct_message) since Facebook's
    private_replies edge carries the same "one reply per comment" constraint
    Instagram's does (confirmed against current Graph API docs — this phase's
    research spike). Not a subclass of MetaMessagingClient: that client is
    hardcoded to graph.instagram.com; Facebook Pages live on
    graph.facebook.com, same Graph API family and auth style (access_token
    query param) as Instagram's, unlike WhatsApp Cloud API's Bearer-header
    convention.
    """

    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or f"https://graph.facebook.com/{settings.META_GRAPH_API_VERSION}"
        self._client = httpx.Client(timeout=30.0)

    def send_private_reply(
        self,
        access_token: str,
        page_id: str,
        comment_id: str,
        text: str,
    ) -> MetaMessageResult:
        """Send a private reply to a Facebook Page comment.

        Endpoint: POST /{page_id}/messages with recipient.comment_id — only
        usable once per comment (subsequent attempts fail the same way
        Instagram's subcode 2534014 does).
        """
        if settings.META_MOCK_PRIVATE_REPLIES:
            return MetaMessageResult(
                success=True,
                provider_message_id=f"mock_fb_message_{comment_id}",
                # A realistic-shaped recipient_id: the real Send API returns
                # the commenter's PSID here, and _record_facebook_psid()
                # persists it onto the lead. Returning a literal "mock" would
                # leave that path untested in mock mode.
                raw_response={
                    "recipient_id": f"mock_psid_{comment_id}",
                    "message_id": f"mock_fb_message_{comment_id}",
                },
            )

        url = f"{self.base_url}/{page_id}/messages"
        params = {"access_token": access_token}
        payload = {"recipient": {"comment_id": comment_id}, "message": {"text": text}}

        try:
            response = self._client.post(url, params=params, json=payload)
        except httpx.NetworkError as exc:
            logger.warning("Facebook messaging network error", extra={"error": str(exc)})
            return MetaMessageResult(success=False, error_code="network_error", error_message=str(exc))
        except httpx.TimeoutException as exc:
            logger.warning("Facebook messaging timeout", extra={"error": str(exc)})
            return MetaMessageResult(success=False, error_code="timeout", error_message="Request timed out")

        return self._handle_response(response, context={"comment_id": comment_id})

    def send_direct_message(
        self,
        access_token: str,
        page_id: str,
        recipient_id: str,
        text: str,
    ) -> MetaMessageResult:
        """Send a plain text message to an open conversation via recipient.id.

        Used after a postback tap or once a user has messaged the Page
        directly, when the standard 24-hour messaging window is open —
        distinct from send_private_reply(), same relationship
        send_direct_message() has to send_private_reply() on the Instagram
        client.

        Endpoint: POST /{page_id}/messages with recipient.id
        """
        if settings.META_MOCK_PRIVATE_REPLIES:
            return MetaMessageResult(
                success=True,
                provider_message_id=f"mock_fb_dm_{recipient_id}",
                raw_response={"recipient_id": recipient_id, "message_id": f"mock_fb_dm_{recipient_id}"},
            )

        url = f"{self.base_url}/{page_id}/messages"
        params = {"access_token": access_token}
        payload = {"recipient": {"id": recipient_id}, "message": {"text": text}}

        try:
            response = self._client.post(url, params=params, json=payload)
        except httpx.NetworkError as exc:
            logger.warning("Facebook direct message network error", extra={"error": str(exc)})
            return MetaMessageResult(success=False, error_code="network_error", error_message=str(exc))
        except httpx.TimeoutException as exc:
            logger.warning("Facebook direct message timeout", extra={"error": str(exc)})
            return MetaMessageResult(success=False, error_code="timeout", error_message="Request timed out")

        return self._handle_response(response, context={"recipient_id": recipient_id})

    def _handle_response(self, response: httpx.Response, context: dict) -> MetaMessageResult:
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
            error_msg = error.get("message", "Facebook API error")
            logger.error(
                "Facebook messaging API error",
                extra={
                    **context,
                    "status_code": response.status_code,
                    "error_code": error.get("code"),
                    "error_subcode": error.get("error_subcode"),
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

        message_id = data.get("id") or data.get("message_id")
        return MetaMessageResult(success=True, provider_message_id=message_id, raw_response=data)

    def close(self) -> None:
        self._client.close()
