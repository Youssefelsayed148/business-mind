import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_TEMPLATE_FIELDS = "name,language,status,category,components,id"
_PHONE_NUMBER_FIELDS = "id,verified_name,display_phone_number,quality_rating"


@dataclass(frozen=True)
class WhatsappManagementResult:
    success: bool
    data: Any = None
    error_message: str | None = None
    meta_error_code: int | None = None
    meta_error_subcode: int | None = None


@dataclass(frozen=True)
class WhatsappPhoneNumberHealth:
    id: str | None
    verified_name: str | None
    display_phone_number: str | None
    quality_rating: str | None
    # Meta's currently accessible phone-number reference does not document
    # these fields. They are parsed only when returned and are never requested.
    messaging_limit_tier: str | None = None
    status: str | None = None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


class WhatsappManagementClient:
    """Synchronous, bearer-authenticated WhatsApp management API client."""

    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or f"https://graph.facebook.com/{settings.META_GRAPH_API_VERSION}"
        self._client = httpx.Client(timeout=30.0)

    @staticmethod
    def _headers(access_token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {access_token}"}

    @staticmethod
    def _decode_response(response: httpx.Response, operation: str) -> WhatsappManagementResult:
        try:
            data = response.json()
        except Exception:
            logger.error(
                "WhatsApp management API returned invalid JSON",
                extra={"operation": operation, "status_code": response.status_code},
            )
            return WhatsappManagementResult(
                success=False,
                error_message=f"Invalid JSON response (HTTP {response.status_code})",
            )

        if response.status_code >= 400 or (isinstance(data, dict) and "error" in data):
            error = data.get("error") if isinstance(data, dict) and isinstance(data.get("error"), dict) else {}
            meta_error_code = _optional_int(error.get("code"))
            meta_error_subcode = _optional_int(error.get("error_subcode"))
            logger.error(
                "WhatsApp management API error",
                extra={
                    "operation": operation,
                    "status_code": response.status_code,
                    "meta_error_code": meta_error_code,
                    "meta_error_subcode": meta_error_subcode,
                },
            )
            return WhatsappManagementResult(
                success=False,
                error_message=error.get("message", "WhatsApp management API error"),
                meta_error_code=meta_error_code,
                meta_error_subcode=meta_error_subcode,
            )

        return WhatsappManagementResult(success=True, data=data)

    @staticmethod
    def _transport_error(operation: str, exc: httpx.HTTPError) -> WhatsappManagementResult:
        logger.warning(
            "WhatsApp management API transport error",
            extra={"operation": operation, "error_type": type(exc).__name__},
        )
        message = "Request timed out" if isinstance(exc, httpx.TimeoutException) else "Network error"
        return WhatsappManagementResult(success=False, error_message=message)

    def create_template(
        self,
        access_token: str,
        waba_id: str,
        name: str,
        language: str,
        category: str,
        components: list[dict],
    ) -> WhatsappManagementResult:
        url = f"{self.base_url}/{waba_id}/message_templates"
        payload = {
            "name": name,
            "language": language,
            "category": category,
            "components": components,
        }
        try:
            response = self._client.post(url, headers=self._headers(access_token), json=payload)
        except httpx.HTTPError as exc:
            return self._transport_error("create_template", exc)
        return self._decode_response(response, "create_template")

    def list_templates(
        self,
        access_token: str,
        waba_id: str,
        *,
        limit: int = 100,
    ) -> WhatsappManagementResult:
        """Fetch every template page using Graph's returned `after` cursor."""
        url = f"{self.base_url}/{waba_id}/message_templates"
        after: str | None = None
        seen_cursors: set[str] = set()
        templates: list[dict] = []

        while True:
            params: dict[str, str | int] = {"fields": _TEMPLATE_FIELDS, "limit": limit}
            if after is not None:
                params["after"] = after
            try:
                response = self._client.get(url, headers=self._headers(access_token), params=params)
            except httpx.HTTPError as exc:
                return self._transport_error("list_templates", exc)

            page_result = self._decode_response(response, "list_templates")
            if not page_result.success:
                return page_result
            page = page_result.data if isinstance(page_result.data, dict) else {}
            page_data = page.get("data") if isinstance(page.get("data"), list) else []
            templates.extend(item for item in page_data if isinstance(item, dict))

            paging = page.get("paging") if isinstance(page.get("paging"), dict) else {}
            cursors = paging.get("cursors") if isinstance(paging.get("cursors"), dict) else {}
            next_after = cursors.get("after") if isinstance(cursors.get("after"), str) else None
            has_next_page = bool(paging.get("next"))
            if not has_next_page or not next_after or next_after in seen_cursors:
                break
            seen_cursors.add(next_after)
            after = next_after

        return WhatsappManagementResult(success=True, data=templates)

    def delete_template_by_name(
        self,
        access_token: str,
        waba_id: str,
        name: str,
    ) -> WhatsappManagementResult:
        url = f"{self.base_url}/{waba_id}/message_templates"
        try:
            response = self._client.delete(
                url,
                headers=self._headers(access_token),
                params={"name": name},
            )
        except httpx.HTTPError as exc:
            return self._transport_error("delete_template_by_name", exc)
        return self._decode_response(response, "delete_template_by_name")

    def get_phone_number_health(
        self,
        access_token: str,
        waba_id: str,
    ) -> WhatsappManagementResult:
        """Read documented health fields for every number attached to a WABA."""
        url = f"{self.base_url}/{waba_id}/phone_numbers"
        try:
            response = self._client.get(
                url,
                headers=self._headers(access_token),
                params={"fields": _PHONE_NUMBER_FIELDS},
            )
        except httpx.HTTPError as exc:
            return self._transport_error("get_phone_number_health", exc)

        result = self._decode_response(response, "get_phone_number_health")
        if not result.success:
            return result
        payload = result.data if isinstance(result.data, dict) else {}
        rows = payload.get("data") if isinstance(payload.get("data"), list) else []
        health = [
            WhatsappPhoneNumberHealth(
                id=row.get("id") if isinstance(row.get("id"), str) else None,
                verified_name=row.get("verified_name") if isinstance(row.get("verified_name"), str) else None,
                display_phone_number=(
                    row.get("display_phone_number") if isinstance(row.get("display_phone_number"), str) else None
                ),
                quality_rating=row.get("quality_rating") if isinstance(row.get("quality_rating"), str) else None,
                messaging_limit_tier=(
                    row.get("messaging_limit_tier") if isinstance(row.get("messaging_limit_tier"), str) else None
                ),
                status=row.get("status") if isinstance(row.get("status"), str) else None,
            )
            for row in rows
            if isinstance(row, dict)
        ]
        return WhatsappManagementResult(success=True, data=health)

    def close(self) -> None:
        self._client.close()
