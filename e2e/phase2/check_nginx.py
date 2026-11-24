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
for path in ("/api/%2573aas/messages", "/API/saas/messages", "/api/saas%2fmessages"):
    check("many-signed-unreached", "POST", MANY, path, "deny_or_unreached")

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

failed = [r for r in results if not r["ok"]]
print(f"SUMMARY nginx_checks total={len(results)} passed={len(results) - len(failed)} failed={len(failed)}")
sys.exit(1 if failed else 0)
