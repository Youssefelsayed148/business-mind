"""Server-side proxy to the Many API (Phase 4A, decision P1).

The browser calls the SaaS API with its session cookie. This module checks who the caller is,
what they may do in the organization, exchanges a signed assertion for a short Many token on the
server, and forwards one allowlisted call. The Many token and the workspace id never reach the
browser. Nothing here touches Instagram code: Instagram is reached only through Many's own
routes, listed in ``many_routes`` for platform staff.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.orm import Session as OrmSession

from app.channels.outbound import UnsafeTarget, resolve_target
from app.core.config import Settings
from app.core.errors import ApiError
from app.db.models import User
from app.identity.sso import mint_assertion

_FORWARDED_REQUEST_HEADERS = ("content-type", "accept")
_RELAYED_RESPONSE_HEADERS = ("content-type", "content-disposition", "retry-after")


class ManyUnavailable(Exception):
    """Many did not answer, answered something unusable, or the target was refused."""


@dataclass(frozen=True)
class ManyResponse:
    status: int
    headers: dict[str, str]
    body: bytes


def send_to_many(
    settings: Settings,
    method: str,
    path_and_query: str,
    headers: dict[str, str],
    body: bytes | None,
) -> ManyResponse:
    """One call to Many over the pinned, policy-checked target (same rules as channel sends)."""
    try:
        url, hostname = resolve_target(settings.many_api_base_url, settings, path=path_and_query)
    except UnsafeTarget as exc:
        raise ManyUnavailable("target refused") from exc
    authority = f"[{hostname}]" if ":" in hostname else hostname
    if url.port is not None:
        authority += f":{url.port}"
    cap = settings.many_proxy_max_response_bytes
    try:
        with (
            httpx.Client(
                follow_redirects=False,
                trust_env=False,
                timeout=httpx.Timeout(
                    settings.many_proxy_timeout_seconds,
                    connect=min(5.0, settings.many_proxy_timeout_seconds),
                ),
            ) as client,
            client.stream(
                method,
                url,
                content=body,
                headers={**headers, "Host": authority, "Accept-Encoding": "identity"},
                extensions={"sni_hostname": hostname},
            ) as response,
        ):
            raw = bytearray()
            for chunk in response.iter_bytes(chunk_size=8192):
                raw.extend(chunk)
                if len(raw) > cap:
                    raise ManyUnavailable("response too large")
            kept = {
                name: response.headers[name]
                for name in _RELAYED_RESPONSE_HEADERS
                if name in response.headers
            }
            return ManyResponse(response.status_code, kept, bytes(raw))
    except httpx.HTTPError as exc:
        raise ManyUnavailable("transport error") from exc


# --- Many session tokens ---------------------------------------------------------------------

_cache: dict[tuple[Any, ...], tuple[str, float]] = {}
_cache_lock = threading.Lock()


def clear_token_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _exchange(settings: Settings, assertion: str) -> tuple[str, int]:
    response = send_to_many(
        settings,
        "POST",
        "/auth/sso/exchange",
        {"content-type": "application/json", "accept": "application/json"},
        json.dumps({"assertion": assertion}).encode("utf-8"),
    )
    if response.status != 200:
        # Many answers one generic message; the reason is in its audit log only.
        raise ManyUnavailable(f"exchange refused ({response.status})")
    try:
        data = json.loads(response.body)
        token = data["access_token"]
        expires_in = int(data.get("expires_in", 600))
    except (ValueError, KeyError, TypeError) as exc:
        raise ManyUnavailable("exchange answer unusable") from exc
    if not isinstance(token, str) or not token:
        raise ManyUnavailable("exchange answer unusable")
    return token, expires_in


def many_token(
    db: OrmSession,
    settings: Settings,
    user: User,
    *,
    org_id: UUID | None,
    staff: bool,
    fingerprint: str,
    session_token_hash: str | None,
) -> str:
    """A Many token for this user and organization, from the cache or a fresh exchange.

    The caller has already checked the user's access in the SaaS database on this request. The
    cache key includes the effective role (and agency), so a role change takes effect at once;
    the token itself lives at most ``many_proxy_token_cache_seconds``.
    """
    key = (user.id, org_id, "staff" if staff else "client", fingerprint)
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None and hit[1] > now:
            return hit[0]
    minted = mint_assertion(
        db,
        settings,
        user,
        scope="staff" if staff else "client",
        org_id=org_id,
        session_token_hash=session_token_hash,
    )
    token, expires_in = _exchange(settings, minted.token)
    lifetime = max(1, min(settings.many_proxy_token_cache_seconds, expires_in - 60))
    with _cache_lock:
        _cache[key] = (token, now + lifetime)
        for stale in [k for k, (_, until) in _cache.items() if until <= now]:
            del _cache[stale]
    return token


def forward(
    settings: Settings,
    *,
    token: str,
    workspace_id: UUID | None,
    method: str,
    path: str,
    query: str,
    request_headers: dict[str, str],
    body: bytes | None,
) -> ManyResponse:
    """Forward one allowlisted call. Only two request headers come from the browser."""
    headers = {
        name: value
        for name, value in request_headers.items()
        if name.lower() in _FORWARDED_REQUEST_HEADERS
    }
    headers["authorization"] = f"Bearer {token}"
    if workspace_id is not None:
        headers["x-workspace-id"] = str(workspace_id)
    target = f"/{path}" + (f"?{query}" if query else "")
    return send_to_many(settings, method, target, headers, body)


def unavailable() -> ApiError:
    return ApiError(502, "MANY_UNAVAILABLE", "The channel service is not available right now.")
