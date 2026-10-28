"""Only the ASGI server may interpret headers after validating the peer."""
import asyncio

import pytest
from starlette.requests import Request
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.services.rate_limit_service import get_client_ip
from app.core.config import settings


def _request(peer="203.0.113.10", forwarded="198.51.100.8"):
    return {"type": "http", "client": (peer, 1234), "scheme": "http", "headers": [
        (b"x-forwarded-for", forwarded.encode()), (b"x-real-ip", b"192.0.2.99"),
    ]}


@pytest.mark.parametrize("legacy_flag", [True, False])
def test_raw_headers_cannot_change_rate_limit_identity(monkeypatch, legacy_flag):
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", legacy_flag)
    assert get_client_ip(Request(_request())) == "203.0.113.10"


@pytest.mark.parametrize("peer,expected", [
    ("203.0.113.10", "203.0.113.10"), ("172.20.0.2", "198.51.100.8"),
])
def test_only_explicit_ingress_peer_can_supply_forwarded_identity(peer, expected):
    observed = []

    async def endpoint(scope, receive, send):
        observed.append(get_client_ip(Request(scope)))

    middleware = ProxyHeadersMiddleware(endpoint, trusted_hosts=["172.20.0.2"])
    asyncio.run(middleware(_request(peer), None, None))
    assert observed == [expected]


def test_trusted_proxy_chain_does_not_accept_spoofed_leftmost_ip():
    observed = []

    async def endpoint(scope, receive, send):
        observed.append(get_client_ip(Request(scope)))

    middleware = ProxyHeadersMiddleware(endpoint, trusted_hosts=["172.20.0.2"])
    asyncio.run(middleware(_request("172.20.0.2", "192.0.2.99, 198.51.100.8"), None, None))
    assert observed == ["198.51.100.8"]
