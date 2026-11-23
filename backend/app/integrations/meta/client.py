import logging

import httpx

from app.core.config import settings
from app.integrations.meta.errors import MetaAPIError

logger = logging.getLogger(__name__)


class MetaGraphClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or f"https://graph.facebook.com/{settings.META_GRAPH_API_VERSION}"
        self._client = httpx.AsyncClient()

    async def get(
        self,
        path: str,
        access_token: str,
        params: dict | None = None,
    ) -> dict:
        url = f"{self.base_url}{path}"
        query = {**(params or {}), "access_token": access_token}
        response = await self._client.get(url, params=query)
        return self._handle_response(response)

    async def post(
        self,
        path: str,
        access_token: str,
        json: dict | None = None,
        params: dict | None = None,
    ) -> dict:
        url = f"{self.base_url}{path}"
        query = {**(params or {}), "access_token": access_token}
        response = await self._client.post(url, params=query, json=json)
        return self._handle_response(response)

    def _handle_response(self, response: httpx.Response) -> dict:
        try:
            data = response.json()
        except Exception:
            raise MetaAPIError("Invalid JSON response", status_code=response.status_code)

        if response.status_code >= 400 or "error" in data:
            error = data.get("error", {})
            raise MetaAPIError(
                error.get("message", "Meta API error"),
                status_code=response.status_code,
                response_body=data,
            )

        return data

    async def close(self):
        await self._client.aclose()
