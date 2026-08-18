import logging

import httpx

from app.core.config import settings
from app.integrations.meta.errors import classify_meta_error

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
    """Synchronous Meta Graph API client for use inside Celery tasks.

    Uses httpx.Client (sync) instead of httpx.AsyncClient to avoid
    event-loop lifecycle issues when called from Celery worker processes.
    """

    def __init__(self, base_url: str | None = None):
        # Instagram API with Instagram Login: messaging endpoints live on
        # graph.instagram.com, not graph.facebook.com. Tokens issued by the
        # Instagram Login flow are rejected by graph.facebook.com.
        self.base_url = base_url or f"https://graph.instagram.com/{settings.META_GRAPH_API_VERSION}"
        self._client = httpx.Client(timeout=30.0)

    def send_private_reply(
        self,
        access_token: str,
        ig_user_id: str,
        comment_id: str,
        text: str,
    ) -> MetaMessageResult:
        """Send a private reply to an Instagram comment.

        Endpoint: POST /{ig_user_id}/messages with recipient.comment_id
        """
        if settings.META_MOCK_PRIVATE_REPLIES:
            return MetaMessageResult(
                success=True,
                provider_message_id=f"mock_message_{comment_id}",
                raw_response={"recipient_id": "mock", "message_id": f"mock_message_{comment_id}"},
            )

        url = f"{self.base_url}/{ig_user_id}/messages"
        params = {"access_token": access_token}
        payload = {"recipient": {"comment_id": comment_id}, "message": {"text": text}}

        try:
            response = self._client.post(url, params=params, json=payload)
        except httpx.NetworkError as exc:
            logger.warning("Meta messaging network error", extra={"error": str(exc)})
            return MetaMessageResult(success=False, error_code="network_error", error_message=str(exc))
        except httpx.TimeoutException as exc:
            logger.warning("Meta messaging timeout", extra={"error": str(exc)})
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
            error_msg = error.get("message", "Meta API error")
            logger.error(
                "Meta private_reply API error",
                extra={
                    "comment_id": comment_id,
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
            )

        message_id = data.get("id") or data.get("message_id")
        return MetaMessageResult(success=True, provider_message_id=message_id, raw_response=data)

    def send_direct_message(
        self,
        access_token: str,
        ig_user_id: str,
        recipient_id: str,
        text: str,
    ) -> MetaMessageResult:
        """Send a plain text DM to an open conversation via recipient.id.

        Used after a postback tap, when the standard 24-hour messaging
        window is open. This is distinct from send_private_reply(), which
        uses recipient.comment_id and may only be used ONCE per comment
        (subsequent attempts fail with Meta error subcode 2534014).

        Endpoint: POST /{ig_user_id}/messages with recipient.id
        """
        if settings.META_MOCK_PRIVATE_REPLIES:
            return MetaMessageResult(
                success=True,
                provider_message_id=f"mock_dm_{recipient_id}",
                raw_response={"recipient_id": recipient_id, "message_id": f"mock_dm_{recipient_id}"},
            )

        url = f"{self.base_url}/{ig_user_id}/messages"
        params = {"access_token": access_token}
        payload = {"recipient": {"id": recipient_id}, "message": {"text": text}}

        try:
            response = self._client.post(url, params=params, json=payload)
        except httpx.NetworkError as exc:
            logger.warning("Meta direct message network error", extra={"error": str(exc)})
            return MetaMessageResult(success=False, error_code="network_error", error_message=str(exc))
        except httpx.TimeoutException as exc:
            logger.warning("Meta direct message timeout", extra={"error": str(exc)})
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
            error_msg = error.get("message", "Meta API error")
            logger.error(
                "Meta direct_message API error",
                extra={
                    "recipient_id": recipient_id,
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
            )

        message_id = data.get("id") or data.get("message_id")
        return MetaMessageResult(success=True, provider_message_id=message_id, raw_response=data)

    def send_follow_prompt_card(
        self,
        access_token: str,
        ig_user_id: str,
        comment_id: str,
        title: str,
        description: str,
        profile_url: str,
        message_id: str,
        button_label: str = "I'm following!",
        recipient_id: str | None = None,
    ) -> MetaMessageResult:
        """Send a follow-prompt template card with a postback button.

        If recipient_id (an IGSID) is provided, the card is sent to the open
        conversation via recipient.id instead of recipient.comment_id. This
        matters because Meta permits only ONE private reply per comment
        (further attempts fail with error subcode 2534014). Once the user
        taps a button, the standard 24-hour messaging window is open, so
        re-prompts must go through recipient.id.

        The button carries a payload encoding the internal follow_prompt
        Message row's id (FOLLOW_CHECK:{message_id}). When tapped, Meta
        delivers a messaging_postbacks webhook event containing this
        payload, which the worker uses to look up the message, check live
        follow status via the User Profile API, and either deliver the
        final message or re-send this same prompt.

        Endpoint: POST /{ig_user_id}/messages with recipient.comment_id
        """
        if settings.META_MOCK_PRIVATE_REPLIES:
            return MetaMessageResult(
                success=True,
                provider_message_id=f"mock_follow_prompt_{comment_id}",
                raw_response={"recipient_id": "mock", "message_id": f"mock_follow_prompt_{comment_id}"},
            )

        url = f"{self.base_url}/{ig_user_id}/messages"
        params = {"access_token": access_token}
        recipient = {"id": recipient_id} if recipient_id else {"comment_id": comment_id}
        payload = {
            "recipient": recipient,
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
                                        "type": "postback",
                                        "title": button_label,
                                        "payload": f"FOLLOW_CHECK:{message_id}",
                                    }
                                ],
                            }
                        ],
                    },
                }
            }
        }
        # profile_url is retained on the campaign for display purposes
        # elsewhere in the dashboard, but is no longer used as a button
        # target now that the button is a postback rather than a web_url link.

        try:
            response = self._client.post(url, params=params, json=payload)
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
            error_msg = error.get("message", "Meta API error")
            logger.error(
                "Meta follow_prompt API error",
                extra={
                    "comment_id": comment_id,
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
            )

        message_id = data.get("id") or data.get("message_id")
        return MetaMessageResult(success=True, provider_message_id=message_id, raw_response=data)

    def reply_to_comment(
        self,
        access_token: str,
        comment_id: str,
        message: str,
    ) -> MetaMessageResult:
        """Post a public reply on an Instagram comment.

        Endpoint: POST /{comment-id}/replies
        Used after a private reply DM is sent, to publicly let the
        commenter know a DM is on its way.
        """
        if settings.META_MOCK_PRIVATE_REPLIES:
            return MetaMessageResult(
                success=True,
                provider_message_id=f"mock_comment_reply_{comment_id}",
                raw_response={"id": f"mock_comment_reply_{comment_id}"},
            )

        url = f"{self.base_url}/{comment_id}/replies"
        params = {"access_token": access_token}
        payload = {"message": message}

        try:
            response = self._client.post(url, params=params, json=payload)
        except httpx.NetworkError as exc:
            logger.warning("Meta comment reply network error", extra={"error": str(exc)})
            return MetaMessageResult(success=False, error_code="network_error", error_message=str(exc))
        except httpx.TimeoutException as exc:
            logger.warning("Meta comment reply timeout", extra={"error": str(exc)})
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
            error_msg = error.get("message", "Meta API error")
            logger.error(
                "Meta comment_reply API error",
                extra={
                    "comment_id": comment_id,
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
            )

        reply_id = data.get("id")
        return MetaMessageResult(success=True, provider_message_id=reply_id, raw_response=data)

    def get_is_user_follow_business(
        self,
        access_token: str,
        ig_scoped_id: str,
    ) -> bool | None:
        """Check whether an Instagram user currently follows the connected
        business account, via the Instagram User Profile API.

        Endpoint: GET /{IGSID}?fields=is_user_follow_business

        Per Meta's docs, this requires "user consent" to have been granted —
        set only once the user has sent a message, or tapped a postback /
        quick-reply / icebreaker button. Calling this immediately after a
        postback tap (as this feature does) satisfies that requirement.

        Returns True/False on success, or None if the call fails (e.g.
        consent not yet granted, network error, invalid token) — callers
        should treat None the same as False (not confirmed following) and
        must never crash on it.
        """
        if settings.META_MOCK_PRIVATE_REPLIES:
            return True

        url = f"{self.base_url}/{ig_scoped_id}"
        params = {"access_token": access_token, "fields": "is_user_follow_business"}

        try:
            response = self._client.get(url, params=params)
        except httpx.NetworkError as exc:
            logger.warning("Follow-status check network error", extra={"error": str(exc), "ig_scoped_id": ig_scoped_id})
            return None
        except httpx.TimeoutException as exc:
            logger.warning("Follow-status check timeout", extra={"error": str(exc), "ig_scoped_id": ig_scoped_id})
            return None

        try:
            data = response.json()
        except Exception:
            logger.warning(
                "Follow-status check invalid JSON",
                extra={"status_code": response.status_code, "ig_scoped_id": ig_scoped_id},
            )
            return None

        if response.status_code >= 400 or "error" in data:
            error = data.get("error", {})
            logger.warning(
                "Follow-status check API error",
                extra={
                    "ig_scoped_id": ig_scoped_id,
                    "status_code": response.status_code,
                    "error_code": error.get("code"),
                    "error_message": error.get("message"),
                    "raw_response": data,
                },
            )
            return None

        value = data.get("is_user_follow_business")
        if isinstance(value, bool):
            return value
        return None

    def close(self):
        """Close the underlying HTTP client."""
        self._client.close()