"""Edge checks THROUGH nginx (unified.conf). Raw paths are sent as-is (http.client does not
normalize), the Host header selects the vhost. Fake/unauthenticated requests only.

A request is an EDGE DENY when it gets 403 + header X-Edge-Deny: 1 + body "denied at the edge".
"""

import http.client
import json
import os
import sys
import uuid

EDGE = (os.environ.get("EDGE_HOST", "nginx"), int(os.environ.get("EDGE_PORT", "80")))
MANY, SAAS_WEB, SAAS_API = "localhost", "saas.localhost", "saas-api.localhost"
UID = str(uuid.uuid4())
results: list[dict] = []


def call(method: str, host: str, path: str, body: bytes | None = None) -> dict:
    conn = http.client.HTTPConnection(*EDGE, timeout=15)
    conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
    conn.putheader("Host", host)
    conn.putheader("Content-Length", str(len(body or b"")))
    conn.putheader("Content-Type", "application/json")
    conn.endheaders(body or b"")
    response = conn.getresponse()
    text = response.read().decode("utf-8", "replace")
    out = {
        "status": response.status,
        "edge_deny": response.getheader("X-Edge-Deny") == "1" and "denied at the edge" in text,
        "body": text[:120].replace("\n", " "),
    }
    conn.close()
    return out


def check(name: str, method: str, host: str, path: str, expect: str) -> None:
    got = call(method, host, path, b"{}" if method == "POST" else None)
    # The apps answer with a JSON error body: Many {"detail": ...}, SaaS {"error": {...}}.
    is_json_detail = got["body"].lstrip().startswith("{") and ('"detail"' in got["body"] or '"error"' in got["body"])
    if expect == "deny":
        ok = got["status"] == 403 and got["edge_deny"]
    elif expect == "app_401_403":
        ok = got["status"] in (401, 403) and not got["edge_deny"] and is_json_detail
    elif expect == "deny_or_unreached":
        ok = got["edge_deny"] or got["status"] in (400, 404)
    elif expect == "app_4xx_json":
        # The app answered with its own JSON error (flag off: 404): reached, not denied at the edge.
        ok = 400 <= got["status"] < 500 and not got["edge_deny"] and is_json_detail
    elif expect == "redirect_or_4xx":
        ok = got["status"] in (307, 308, 404, 405) and not got["edge_deny"]
    elif expect == "not_found":
        ok = got["status"] in (404, 405) and not got["edge_deny"]
    elif expect == "ok":
        ok = got["status"] < 500 and not got["edge_deny"]
    else:
        raise ValueError(expect)
    results.append({"check": name, "method": method, "host": host, "path": path, "expect": expect, **got, "ok": ok})
    print(json.dumps(results[-1]), flush=True)


# (a) Many's signed service-to-service routes are denied at the edge, in every spelling.
for path in (
    "/api/saas/messages",
    "/saas/messages",
    "//api/saas/messages",
    "/api/%73aas/messages",
    "/api/saas/../saas/messages",
    "/api/./saas/messages",
    "/%73aas/messages",
    "/api/saas/messages/",
    "/api/saas/connections/x/health",
    "/saas/connections/x/health",
):
    check("many-signed", "POST" if path.endswith("messages") else "GET", MANY, path, "deny")
# Spellings that do not normalize to the signed prefix must simply not reach the handler.
for path in ("/api/%2573aas/messages", "/api/saas%2fmessages"):
    check("many-signed-unreached", "POST", MANY, path, "deny_or_unreached")
# Mixed-case spellings: nginx prefix locations are case-sensitive, so case-insensitive
# regex locations must deny them at the edge.
for path in ("/API/saas/messages", "/Api/saas/messages"):
    check("many-signed-mixedcase", "POST", MANY, path, "deny")

# SaaS signed events endpoint: denied on BOTH hosts that reach saas-api.
for host in (SAAS_API, SAAS_WEB):
    for path in (
        "/api/channels/manyosiris/events",
        "//api/channels/manyosiris/events",
        "/api/%63hannels/manyosiris/events",
        "/api/channels/%6danyosiris/events",
        "/api/channels/%6Danyosiris/%65vents",
        "/api/channels/../channels/manyosiris/events",
        "/api/./channels/manyosiris/events",
        "/api/channels/manyosiris/events/",
    ):
        check("saas-signed-events", "POST", host, path, "deny")
    check("saas-signed-events-unreached", "POST", host, "/api/channels%2fmanyosiris%2fevents", "deny_or_unreached")
    for path in ("/API/channels/manyosiris/events", "/Api/channels/manyosiris/events"):
        check("saas-signed-events-mixedcase", "POST", host, path, "deny")
    check("saas-signed-events-mixedcase-segment", "POST", host, "/api/CHANNELS/manyosiris/events", "deny_or_unreached")

# (b) Delegation admin routes (JWT) must reach the app and get ITS 401/403, not the edge deny.
for path in (
    f"/instagram/accounts/{UID}/saas-delegation",
    f"/api/instagram/accounts/{UID}/saas-delegation",
    f"/api/whatsapp/accounts/{UID}/saas-delegation",
    f"/api/facebook/accounts/{UID}/saas-delegation",
):
    check("many-admin-not-shadowed", "GET", MANY, path, "app_401_403")
# SaaS admin API (session auth) is not shadowed either.
check("saas-admin-not-shadowed", "GET", SAAS_API, "/api/v1/platform/channel-connections", "app_401_403")
check("saas-admin-via-web-not-shadowed", "GET", SAAS_WEB, "/api/v1/platform/channel-connections", "app_401_403")

# Routing sanity (the vhosts reach the right services).
check("many-health", "GET", MANY, "/health", "ok")
check("many-dashboard", "GET", MANY, "/", "ok")
check("saas-api-ready", "GET", SAAS_API, "/ready", "ok")
check("saas-web", "GET", SAAS_WEB, "/", "ok")

# (c) SSO exchange (Phase 3, design 2.6). The stack runs with the flags off, so the app answers 404;
# with SSO on it would answer 400/401. Either way it is the APP answering, never an edge deny.
for path in (
    "/auth/sso/exchange",
    "//auth/sso/exchange",
    "/auth/./sso/exchange",
    "/auth/sso/../sso/exchange",
    "/auth/%73so/exchange",
    "/auth/sso/%65xchange",
):
    check("sso-exchange-reaches-the-app", "POST", MANY, path, "app_4xx_json")
# Mixed case: the regex twin applies the same limit and forwards as written; FastAPI is case
# sensitive, so the handler is not reached and the app answers 404.
for path in ("/AUTH/sso/exchange", "/Auth/SSO/Exchange", "/auth/SSO/exchange", "/auth/sso/EXCHANGE"):
    check("sso-exchange-mixedcase", "POST", MANY, path, "app_4xx_json")
check("sso-exchange-trailing-slash", "POST", MANY, "/auth/sso/exchange/", "redirect_or_4xx")
# Not routed to Many on the SaaS hosts (404 from the SaaS API or from Next, never 2xx).
for host in (SAAS_API, SAAS_WEB):
    for path in ("/auth/sso/exchange", "/AUTH/sso/exchange"):
        check("sso-exchange-not-on-saas-hosts", "POST", host, path, "not_found")
# SaaS issuing routes are ordinary app routes on the SaaS hosts (flag off: the app answers 404).
for host in (SAAS_API, SAAS_WEB):
    check("sso-issuer-routes-reach-the-saas-app", "POST", host, "/api/v1/sso/assertions", "app_4xx_json")
    check("sso-issuer-authorize-reaches-the-saas-app", "GET", host, "/api/v1/sso/authorize", "app_4xx_json")
# The signed routes stay denied right next to the new location.
check("signed-still-denied-after-sso", "POST", MANY, "/api/saas/messages", "deny")


def burst(name: str, host: str, path: str, total: int = 30) -> None:
    """The exchange zone limits per client address, so a burst gets 429s from the edge itself.

    The earlier exchange checks already spent part of the burst allowance, so the first requests
    here may be limited too; what matters is that the 429s come from nginx (a plain error page,
    never the app's JSON) and that none of the answers is a 2xx.
    """
    answers = [call("POST", host, path, b"{}") for _ in range(total)]
    edge_429 = [a for a in answers if a["status"] == 429 and not a["body"].lstrip().startswith("{")]
    ok = len(edge_429) >= 5 and not any(200 <= a["status"] < 300 for a in answers)
    results.append({"check": name, "method": "POST", "host": host, "path": path, "expect": "rate_limited",
                    "status": 429 if edge_429 else answers[-1]["status"], "edge_deny": False,
                    "body": f"{len(edge_429)} of {total} requests answered 429 by the edge", "ok": ok})
    print(json.dumps(results[-1]), flush=True)


# Last on purpose: it trips the limiter for this client address on the exchange path only.
burst("sso-exchange-rate-limited-at-the-edge", MANY, "/auth/sso/exchange")

failed = [r for r in results if not r["ok"]]
print(f"SUMMARY nginx_checks total={len(results)} passed={len(results) - len(failed)} failed={len(failed)}")
sys.exit(1 if failed else 0)
