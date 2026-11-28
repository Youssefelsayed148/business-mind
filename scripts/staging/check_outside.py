#!/usr/bin/env python3
"""Checks of the edge from OUTSIDE the host (Phase 6B). Standard library only; sends nothing secret.

  python scripts/staging/check_outside.py --many many.example.com --saas-web saas.example.com \
      --saas-api api.example.com [--resolve many.example.com=127.0.0.1:8443 ...] [--min-days 14]

Checks: port 80 redirects each host to HTTPS; the certificate chain verifies for each host with the
system roots and has at least --min-days left; HSTS is sent; every signed or exchange route is an EDGE
DENY (403 + X-Edge-Deny: 1) over HTTPS; health answers 200 on Many and the SaaS API.
--resolve host=ip:port (repeatable) points a name at a test server, like curl --resolve (port is the
HTTPS port; the HTTP port is --http-port). Exit 0 when every check passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import http.client
import socket
import ssl
import sys
import time
from dataclasses import dataclass

DENY_BODY = "denied at the edge"


@dataclass
class Target:
    host: str
    ip: str
    https_port: int
    http_port: int


def _request(
    t: Target, scheme: str, method: str, path: str, ctx: ssl.SSLContext | None = None
) -> tuple[int, dict[str, str], str]:
    if scheme == "https":
        # Connect to the (possibly overridden) address, verify the certificate for the real host name.
        raw = socket.create_connection((t.ip, t.https_port), timeout=15)
        conn = http.client.HTTPConnection(t.ip, t.https_port, timeout=15)
        conn.sock = (ctx or ssl.create_default_context()).wrap_socket(raw, server_hostname=t.host)
    else:
        conn = http.client.HTTPConnection(t.ip, t.http_port, timeout=15)
    try:
        conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        conn.putheader("Host", t.host)
        conn.putheader("Content-Length", "0")
        conn.endheaders()
        response = conn.getresponse()
        body = response.read().decode("utf-8", "replace")
        return response.status, {k.lower(): v for k, v in response.getheaders()}, body
    finally:
        conn.close()


def days_left(t: Target, ctx: ssl.SSLContext | None = None) -> float:
    context = ctx or ssl.create_default_context()
    with socket.create_connection((t.ip, t.https_port), timeout=15) as raw:
        with context.wrap_socket(raw, server_hostname=t.host) as tls:
            cert = tls.getpeercert()
    expires = ssl.cert_time_to_seconds(cert["notAfter"])
    return (expires - time.time()) / 86400


def run(
    targets: dict[str, Target], min_days: float, ctx: ssl.SSLContext | None = None
) -> list[tuple[bool, str]]:
    out: list[tuple[bool, str]] = []

    def check(ok: bool, text: str) -> None:
        out.append((ok, text))

    many, web, api = targets["many"], targets["saas_web"], targets["saas_api"]
    for name, t in targets.items():
        try:
            status, headers, _ = _request(t, "http", "GET", "/some/page?x=1")
            location = headers.get("location", "")
            check(
                status == 301 and location == f"https://{t.host}/some/page?x=1",
                f"{name}: port 80 redirects to https (got {status} {location!r})",
            )
        except OSError as exc:
            check(False, f"{name}: port 80 answered nothing ({exc})")
        try:
            left = days_left(t, ctx)
            check(left >= min_days, f"{name}: certificate verifies, {left:.0f} days left (need {min_days:.0f})")
            _, headers, _ = _request(t, "https", "GET", "/", ctx)
            check("strict-transport-security" in headers, f"{name}: HSTS header present")
        except (OSError, ssl.SSLError) as exc:
            check(False, f"{name}: https/certificate check failed ({exc})")

    denied = [
        (many, "POST", "/auth/sso/exchange"),
        (many, "POST", "/api/auth/sso/exchange"),
        (many, "POST", "/api/saas/messages"),
        (many, "POST", "/saas/messages"),
        (web, "POST", "/api/channels/manyosiris/events"),
        (api, "POST", "/api/channels/manyosiris/events"),
    ]
    for t, method, path in denied:
        try:
            status, headers, body = _request(t, "https", method, path, ctx)
            ok = status == 403 and headers.get("x-edge-deny") == "1" and DENY_BODY in body
            check(ok, f"deny over https: {t.host} {method} {path} (got {status})")
        except (OSError, ssl.SSLError) as exc:
            check(False, f"deny over https: {t.host} {path} failed ({exc})")
    for t, path in ((many, "/health"), (api, "/ready")):
        try:
            status, _, _ = _request(t, "https", "GET", path, ctx)
            check(status == 200, f"health: {t.host}{path} answers 200 (got {status})")
        except (OSError, ssl.SSLError) as exc:
            check(False, f"health: {t.host}{path} failed ({exc})")
    return out


def _parse_resolve(items: list[str]) -> dict[str, tuple[str, int]]:
    mapping: dict[str, tuple[str, int]] = {}
    for item in items:
        host, _, rest = item.partition("=")
        ip, _, port = rest.partition(":")
        mapping[host] = (ip, int(port or 443))
    return mapping


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--many", required=True)
    ap.add_argument("--saas-web", required=True)
    ap.add_argument("--saas-api", required=True)
    ap.add_argument("--resolve", action="append", default=[])
    ap.add_argument("--http-port", type=int, default=80)
    ap.add_argument("--min-days", type=float, default=14)
    args = ap.parse_args(argv)
    resolve = _parse_resolve(args.resolve)

    def target(host: str) -> Target:
        ip, port = resolve.get(host, (host, 443))
        return Target(host, ip, port, args.http_port)

    targets = {
        "many": target(args.many),
        "saas_web": target(args.saas_web),
        "saas_api": target(args.saas_api),
    }
    results = run(targets, args.min_days)
    for ok, text in results:
        print(("PASS " if ok else "FAIL ") + text)
    failed = sum(1 for ok, _ in results if not ok)
    print(f"SUMMARY {len(results) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
