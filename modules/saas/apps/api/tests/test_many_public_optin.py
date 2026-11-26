# ruff: noqa: F811
"""The public WhatsApp opt-in call through the Many proxy (Phase 4C). A fake Many answers.

It is the only call that needs no login, so the checks here are strict: off means unknown route,
only one tiny JSON shape goes through, nothing from the browser except the phone number is
forwarded, the caller's address travels in X-Forwarded-For, the limits are enforced here, and
Many's failures never leak.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.identity import many_proxy, many_router
from tests.test_many_proxy import (  # noqa: F401  (fixtures)
    FakeMany,
    many,
    proxy_app,
    proxy_app_client,
    proxy_settings,
)

TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJhIjoxfQ.c2lnbmF0dXJl"
PATH = f"/api/v1/many/public/whatsapp/opt-in/{TOKEN}"
OK = many_proxy.ManyResponse(
    202,
    {"content-type": "application/json"},
    b'{"accepted":true,"message":"Open WhatsApp.","click_to_chat_url":"https://wa.me/1"}',
)


def _post(app: FastAPI, body: Any, ip: str, path: str = PATH) -> Any:
    client = proxy_app_client(app)
    return client.post(
        path,
        content=body if isinstance(body, bytes) else json.dumps(body),
        headers={"content-type": "application/json", "x-forwarded-for": ip},
    )


def test_off_answers_like_an_unknown_route(v2_app: FastAPI, db: Session, many: FakeMany) -> None:
    v2_app.dependency_overrides[get_settings] = lambda: proxy_settings(many_proxy_enabled=False)
    response = _post(v2_app, {"phone": "+201001234567"}, "203.0.113.1")
    assert response.status_code == 404 and response.json() == {"detail": "Not Found"}
    assert many.calls == []


def test_a_visitor_without_a_login_reaches_many_with_only_the_phone(
    proxy_app: FastAPI, db: Session, many: FakeMany
) -> None:
    many.plan.append(OK)
    response = _post(proxy_app, {"phone": " +201001234567 "}, "203.0.113.2, 10.0.0.1")
    assert response.status_code == 202 and response.json()["accepted"] is True
    assert len(many.calls) == 1  # no token exchange: this call has no login
    call = many.calls[0]
    assert call["method"] == "POST" and call["path"] == f"/public/whatsapp/opt-in/{TOKEN}"
    assert json.loads(call["body"]) == {"phone": "+201001234567"}
    headers = {k.lower(): v for k, v in call["headers"].items()}
    assert "authorization" not in headers and "x-workspace-id" not in headers
    assert "cookie" not in headers
    assert headers["x-forwarded-for"] == "203.0.113.2"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[]",
        b'{"phone": 5}',
        b'{"phone": "0100123456"}',
        b'{"phone": "+20 100 123"}',
        b'{"phone": "+2010012345678901234567"}',
        b'{"phone": "+201001234567", "extra": 1}',
        b"{}",
        b"",
    ],
)
def test_anything_but_a_plain_phone_is_refused_before_many(
    proxy_app: FastAPI, db: Session, many: FakeMany, body: bytes
) -> None:
    response = _post(proxy_app, body, "203.0.113.3")
    assert response.status_code == 422, response.text
    assert many.calls == []


@pytest.mark.parametrize("token", ["short", "a b" * 10, "x" * 1600, "a..b%2F..%2F" + "c" * 20])
def test_a_token_that_is_not_token_shaped_is_an_unknown_route(
    proxy_app: FastAPI, db: Session, many: FakeMany, token: str
) -> None:
    response = _post(
        proxy_app,
        {"phone": "+201001234567"},
        "203.0.113.4",
        f"/api/v1/many/public/whatsapp/opt-in/{token}",
    )
    assert response.status_code in (404, 405)
    assert many.calls == []


def test_the_address_limit_is_enforced_here(
    proxy_app: FastAPI, db: Session, many: FakeMany
) -> None:
    ip = "198.51.100.7"
    for _ in range(many_router.OPT_IN_IP_LIMIT):
        many.plan.append(OK)
        assert _post(proxy_app, {"phone": "+201001234567"}, ip).status_code == 202
    refused = _post(proxy_app, {"phone": "+201001234567"}, ip)
    assert refused.status_code == 429 and refused.json()["error"]["code"] == "RATE_LIMITED"
    assert len(many.calls) == many_router.OPT_IN_IP_LIMIT
    many.plan.append(OK)
    assert _post(proxy_app, {"phone": "+201001234567"}, "198.51.100.8").status_code == 202


def test_many_answers_are_relayed_or_hidden(
    proxy_app: FastAPI, db: Session, many: FakeMany
) -> None:
    many.plan.append(
        many_proxy.ManyResponse(
            404,
            {"content-type": "application/json"},
            b'{"detail":"Opt-in link is invalid or expired"}',
        )
    )
    gone = _post(proxy_app, {"phone": "+201001234567"}, "203.0.113.5")
    assert gone.status_code == 404 and "invalid or expired" in gone.text
    many.plan.append(
        many_proxy.ManyResponse(500, {"content-type": "text/plain"}, b"Traceback secret detail")
    )
    broken = _post(proxy_app, {"phone": "+201001234567"}, "203.0.113.6")
    assert broken.status_code == 502 and "secret" not in broken.text
    many.plan.append(many_proxy.ManyUnavailable("down"))
    down = _post(proxy_app, {"phone": "+201001234567"}, "203.0.113.7")
    assert down.status_code == 502 and down.json()["error"]["code"] == "MANY_UNAVAILABLE"


def test_the_public_path_is_still_closed_to_the_logged_in_proxy(
    proxy_app: FastAPI, db: Session, many: FakeMany
) -> None:
    # The generic proxy never forwards /public; this call has its own route above.
    assert many_routes_match_public_is_none()


def many_routes_match_public_is_none() -> bool:
    from app.identity import many_routes

    return all(
        many_routes.match(method, f"public/whatsapp/opt-in/{TOKEN}", audience) is None
        for method in ("POST", "GET")
        for audience in (many_routes.ORG, many_routes.GLOBAL)
    )
