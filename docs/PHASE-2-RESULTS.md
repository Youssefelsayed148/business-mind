# Phase 2 results (2026-11-24, Claude Code)

Commands and observed output only. Branch `phase-2/one-infrastructure`, PR #3. Throwaway stacks, fake secrets, mock Meta, no real Meta/OpenAI calls.

## 1. SaaS full suite, allowlist empty, DB name ending `_test`
Command: `CHANNEL_INTERNAL_ALLOWED_HOSTS= bash ~/phase2/bin/p2run.sh saas full_test` (WSL, `unshare -rn` no-egress netns, Docker pg17 via unix-socket bridge; `APP_ENV=test ENVIRONMENT=test`, DB `saas_p2_full_test`, PGHOST/PGPORT set).

Result: **1277 passed, 0 failed, 0 skipped, 0 errors** in 1823.62 s. Per junit, the new `test_internal_channel_policy.py` accounts for 61 passed; **excluding it, 1216 passed / 0 failed** (Phase 1b's 1215 passed / 1 failed became 1216 / 0 once the DB name and socket env were right). A first attempt of this run produced 1151 connection errors because the socket bridge had died when WSL restarted. That was a harness fault, not a test result; the run was repeated after removing the stale socket.

## 2. Six compose e2e cases (`docker-compose.phase2-e2e.yml`, project `p2e2e`)
Sequence: `down -v`, `up -d --build`, `run --rm --no-deps driver`. Network `internal: true`.

### Health checks
| Service | State / health |
|---|---|
| many-api | running, healthy; `GET /health` 200 |
| saas-api | running, healthy; `GET /ready` 200 |
| pg15, pg17, redis | running, healthy |
| many-worker, saas-worker, mock-meta | running (no healthcheck defined) |
| pki, many-migrate, saas-migrate, saas-seed, many-seed | exited 0 |

Startup log lines: many-api and many-worker print `Internal channel host allowlist enabled: saas-api`; saas-api and saas-worker print `Internal channel host allowlist enabled: many-api`.

### Driver output (verbatim)
```
{"case": 1, "platform": "instagram", "delegation": "ON", "channel_ref": "17840e2e0001", "webhook_http": 200, "many_forward_events": [{"status": "sent", "attempts": 1, "last_error": null}, {"status": "sent", "attempts": 1, "last_error": null}], "saas_channel_events_delta": 2, "many_outbound_from_saas": [{"status": "sent"}], "mock_meta_requests": [{"host": "graph.instagram.com", "path": "/v26.0/17840e2e0001/messages", "body": {"recipient": {"id": "900010011"}, "message": {"text": "I don't have that information. I can connect you with our team in the inbox, or contact our support team."}}}], "passed": true}
{"case": 2, "platform": "whatsapp", "delegation": "ON", "channel_ref": "e2ewa0001", "webhook_http": 200, "many_forward_events": [{"status": "sent", "attempts": 1, "last_error": null}, {"status": "sent", "attempts": 1, "last_error": null}], "saas_channel_events_delta": 2, "many_outbound_from_saas": [{"status": "sent"}], "mock_meta_requests": [{"host": "graph.facebook.com", "path": "/v26.0/e2ewa0001/messages", "body": {"messaging_product": "whatsapp", "to": "16315551002", "type": "text", "text": {"body": "I don't have that information. I can connect you with our team in the inbox, or contact our support team."}}}], "passed": true}
{"case": 3, "platform": "messenger", "delegation": "ON", "channel_ref": "e2efb0001", "webhook_http": 200, "many_forward_events": [{"status": "sent", "attempts": 1, "last_error": null}, {"status": "sent", "attempts": 1, "last_error": null}], "saas_channel_events_delta": 2, "many_outbound_from_saas": [{"status": "sent"}], "mock_meta_requests": [{"host": "graph.facebook.com", "path": "/v26.0/e2efb0001/messages", "body": {"recipient": {"id": "900030011"}, "message": {"text": "I don't have that information. I can connect you with our team in the inbox, or contact our support team."}}}], "passed": true}
{"case": 4, "platform": "instagram", "delegation": "OFF", "channel_ref": "17840e2e0002", "webhook_http": 200, "many_forward_events": [], "saas_channel_events_delta": 0, "many_outbound_from_saas": [], "mock_meta_requests": [], "passed": true}
{"case": 5, "platform": "whatsapp", "delegation": "OFF", "channel_ref": "e2ewa0002", "webhook_http": 200, "many_forward_events": [], "saas_channel_events_delta": 0, "many_outbound_from_saas": [], "mock_meta_requests": [], "passed": true}
{"case": 6, "platform": "messenger", "delegation": "OFF", "channel_ref": "e2efb0002", "webhook_http": 200, "many_forward_events": [], "saas_channel_events_delta": 0, "many_outbound_from_saas": [], "mock_meta_requests": [], "passed": true}
SUMMARY case1=PASS case2=PASS case3=PASS case4=PASS case5=PASS case6=PASS
```

### Destination of every signed call
Taken from the receiving container's access log, with the source IP mapped to a service via `docker inspect`. Container IPs: many-api 192.168.32.10, many-worker .9, saas-api .7, saas-worker .6, mock-meta .4. The webhook sender is .8, the driver (inferred; that `--rm` container no longer exists to inspect).

| Signed call | Source | Destination service (host in the stored URL) | Count in this run |
|---|---|---|---|
| `POST /api/channels/manyosiris/events` | many-worker (.9) | **saas-api** (`http://saas-api:8000`) | 6 |
| `POST /api/saas/messages` | saas-worker (.6) | **many-api** (`http://many-api:8000`) | 3 |
| `POST /webhooks/meta` (mock Meta webhook, HMAC-signed with the per-run fake app secret) | driver (.8) | many-api | 6 |
| Meta send `/v26.0/<id>/messages` | many-worker | mock-meta as `graph.instagram.com` / `graph.facebook.com` | 3 |

Delegation-OFF cases (4 to 6): 0 forwards, 0 SaaS events, 0 Meta calls.

Access-log lines (POST only, health checks excluded):
```
many-api-1  | INFO:     192.168.32.8:54732 - "POST /webhooks/meta HTTP/1.1" 200 OK
many-api-1  | INFO:     192.168.32.6:32886 - "POST /api/saas/messages HTTP/1.1" 202 Accepted
saas-api-1  | INFO:     192.168.32.9:44582 - "POST /api/channels/manyosiris/events HTTP/1.1" 202 Accepted
saas-api-1  | INFO:     192.168.32.9:44596 - "POST /api/channels/manyosiris/events HTTP/1.1" 202 Accepted
saas-api-1  | INFO:     192.168.32.9:44602 - "POST /api/channels/manyosiris/events HTTP/1.1" 202 Accepted
saas-api-1  | INFO:     192.168.32.9:44614 - "POST /api/channels/manyosiris/events HTTP/1.1" 202 Accepted
many-api-1  | INFO:     192.168.32.8:54734 - "POST /webhooks/meta HTTP/1.1" 200 OK
many-api-1  | INFO:     192.168.32.6:32896 - "POST /api/saas/messages HTTP/1.1" 202 Accepted
saas-api-1  | INFO:     192.168.32.9:44618 - "POST /api/channels/manyosiris/events HTTP/1.1" 202 Accepted
saas-api-1  | INFO:     192.168.32.9:44630 - "POST /api/channels/manyosiris/events HTTP/1.1" 202 Accepted
many-api-1  | INFO:     192.168.32.8:54746 - "POST /webhooks/meta HTTP/1.1" 200 OK
many-api-1  | INFO:     192.168.32.6:32902 - "POST /api/saas/messages HTTP/1.1" 202 Accepted
many-api-1  | INFO:     192.168.32.8:44426 - "POST /webhooks/meta HTTP/1.1" 200 OK
many-api-1  | INFO:     192.168.32.8:39052 - "POST /webhooks/meta HTTP/1.1" 200 OK
many-api-1  | INFO:     192.168.32.8:52202 - "POST /webhooks/meta HTTP/1.1" 200 OK
```
mock-meta:
```
mock-meta-1  | mock-meta POST graph.instagram.com /v26.0/17840e2e0001/messages
mock-meta-1  | mock-meta POST graph.facebook.com /v26.0/e2ewa0001/messages
mock-meta-1  | mock-meta POST graph.facebook.com /v26.0/e2efb0001/messages
```

## 3. Other checks (see MERGE-PROGRESS)
Many full suite 1007/0/0; new tests 61 + 61 passed; SaaS ruff/format/mypy clean; policy-copy and both contract-copy checks OK; alembic heads Many `0030_meta_account_erasure`, SaaS `0031_contact_erasure`.

## 4. Phase 2b (branch `phase-2b/unified-compose`, 2026-11-24)

### 4.1 Mixed-DNS fix (commit ddb4051) and CGNAT tests (049b975)
A listed host must now resolve ONLY to RFC1918/ULA addresses; any public or other address in the answer rejects the whole answer. Observed: policy tests 77 passed on each side (Many and SaaS); SaaS `ruff check` clean, `ruff format --check` clean, `mypy` no issues; `check_policy_copies.py` OK; the six compose e2e cases of section 2's stack passed again after the change. CGNAT/Tailscale `100.64.0.0/10` answers are rejected for a listed host (tests added).

### 4.2 The e2e runs in development over http
Both e2e stacks (section 2 and 4.3) run in development/test with `http://` internal URLs. The production-HTTPS rule is therefore covered by UNIT tests only:
- both sides: `test_empty_and_production_tls` (`parse_url(..., require_https=True)` rejects `http://saas-api` and accepts `https://saas-api`);
- Many: `test_many_validation_integration` (`APP_ENV=production`: `https://saas-api` accepted, `http://` and unlisted names rejected);
- SaaS: `test_saas_validation_and_pinning` (`Settings(environment="production")`, `resolve_target` with https hosts).
Production also needs https internal URLs, an open deployment decision (`docs/DEPLOY-OUTLINE.md`).

### 4.3 Unified stack through nginx (`scripts/dev-up.sh test`, project `unified-e2e`, no-egress overlay, mock Meta only)
Command: `NO_BUILD=1 KEEP=1 bash scripts/dev-up.sh test` (images built beforehand; `NO_BUILD=1` only because the registry was unreachable for a metadata lookup). Result: `TEST PASSED`.

Six cases (webhooks enter THROUGH nginx at `http://nginx`, default vhost = Many):
```
{"case": 1, "platform": "instagram", "delegation": "ON", "channel_ref": "17840e2e0001", "webhook_http": 200, "many_forward_events": [{"status": "sent", "attempts": 1, "last_error": null}, {"status": "sent", "attempts": 1, "last_error": null}, {"status": "sent", "attempts": 1, "last_error": null}], "saas_channel_events_delta": 2, "many_outbound_from_saas": [{"status": "sent"}], "mock_meta_requests": [{"host": "graph.instagram.com", "path": "/v26.0/17840e2e0001/messages", "body": {"recipient": {"id": "900010011"}, "message": {"text": "I don't have that information. I can connect you with our team in the inbox, or contact our support team."}}}], "passed": true}
{"case": 2, "platform": "whatsapp", "delegation": "ON", "channel_ref": "e2ewa0001", "webhook_http": 200, "many_forward_events": [{"status": "sent", "attempts": 1, "last_error": null}, {"status": "sent", "attempts": 1, "last_error": null}, {"status": "sent", "attempts": 1, "last_error": null}], "saas_channel_events_delta": 2, "many_outbound_from_saas": [{"status": "sent"}], "mock_meta_requests": [{"host": "graph.facebook.com", "path": "/v26.0/e2ewa0001/messages", "body": {"messaging_product": "whatsapp", "to": "16315551002", "type": "text", "text": {"body": "I don't have that information. I can connect you with our team in the inbox, or contact our support team."}}}], "passed": true}
{"case": 3, "platform": "messenger", "delegation": "ON", "channel_ref": "e2efb0001", "webhook_http": 200, "many_forward_events": [{"status": "sent", "attempts": 1, "last_error": null}, {"status": "sent", "attempts": 1, "last_error": null}, {"status": "sent", "attempts": 1, "last_error": null}], "saas_channel_events_delta": 2, "many_outbound_from_saas": [{"status": "sent"}], "mock_meta_requests": [{"host": "graph.facebook.com", "path": "/v26.0/e2efb0001/messages", "body": {"recipient": {"id": "900030011"}, "message": {"text": "I don't have that information. I can connect you with our team in the inbox, or contact our support team."}}}], "passed": true}
{"case": 4, "platform": "instagram", "delegation": "OFF", "channel_ref": "17840e2e0002", "webhook_http": 200, "many_forward_events": [], "saas_channel_events_delta": 0, "many_outbound_from_saas": [], "mock_meta_requests": [], "passed": true}
{"case": 5, "platform": "whatsapp", "delegation": "OFF", "channel_ref": "e2ewa0002", "webhook_http": 200, "many_forward_events": [], "saas_channel_events_delta": 0, "many_outbound_from_saas": [], "mock_meta_requests": [], "passed": true}
{"case": 6, "platform": "messenger", "delegation": "OFF", "channel_ref": "e2efb0002", "webhook_http": 200, "many_forward_events": [], "saas_channel_events_delta": 0, "many_outbound_from_saas": [], "mock_meta_requests": [], "passed": true}
SUMMARY case1=PASS case2=PASS case3=PASS case4=PASS case5=PASS case6=PASS
```
Driver note: this stack runs celery beat, whose periodic health sweep adds `channel.status` events to SaaS (observed: three, one per delegated connection, at the minute boundary). The first attempt of this run failed case 6 because the driver counted ALL SaaS event types. The overlay now sets `SAAS_EVENT_TYPE_LIKE=message.%` (default `%` = original behaviour). No application code was involved.

Health and config checks:
- `nginx -t`: `the configuration file /etc/nginx/nginx.conf syntax is ok` / `test is successful`.
- Services: many-api, many-dashboard, saas-api, saas-web, nginx, pg15, pg17, redis `healthy`; many-worker, many-beat, saas-worker, mock-meta `running`; one-shots exited 0.
- `docker compose config`: base, base + e2e, base + prod all render; the base nginx port is `host_ip: 127.0.0.1`, published 8080 (the e2e overlay publishes nothing).
- `git diff origin/main -- nginx/default.conf`: empty (never edited). No migration file changed.

### 4.4 Edge checks through nginx (`e2e/phase2/check_nginx.py`): 41 total, 41 passed
(a) Signed routes are denied: HTTP 403, header `X-Edge-Deny: 1`, body `denied at the edge`. (b) JWT/session admin routes reach the app and get ITS 401 (JSON error body, no edge-deny header). Raw paths are sent as-is (no client-side normalisation).

| # | check | host | request | expected | status | edge deny | result |
|---|---|---|---|---|---|---|---|
| 1 | many-signed | `localhost` | `POST /api/saas/messages` | deny | 403 | yes | PASS |
| 2 | many-signed | `localhost` | `POST /saas/messages` | deny | 403 | yes | PASS |
| 3 | many-signed | `localhost` | `POST //api/saas/messages` | deny | 403 | yes | PASS |
| 4 | many-signed | `localhost` | `POST /api/%73aas/messages` | deny | 403 | yes | PASS |
| 5 | many-signed | `localhost` | `POST /api/saas/../saas/messages` | deny | 403 | yes | PASS |
| 6 | many-signed | `localhost` | `POST /api/./saas/messages` | deny | 403 | yes | PASS |
| 7 | many-signed | `localhost` | `POST /%73aas/messages` | deny | 403 | yes | PASS |
| 8 | many-signed | `localhost` | `GET /api/saas/messages/` | deny | 403 | yes | PASS |
| 9 | many-signed | `localhost` | `GET /api/saas/connections/x/health` | deny | 403 | yes | PASS |
| 10 | many-signed | `localhost` | `GET /saas/connections/x/health` | deny | 403 | yes | PASS |
| 11 | many-signed-unreached | `localhost` | `POST /api/%2573aas/messages` | deny_or_unreached | 404 | no | PASS |
| 12 | many-signed-unreached | `localhost` | `POST /API/saas/messages` | deny_or_unreached | 404 | no | PASS |
| 13 | many-signed-unreached | `localhost` | `POST /api/saas%2fmessages` | deny_or_unreached | 403 | yes | PASS |
| 14 | saas-signed-events | `saas-api.localhost` | `POST /api/channels/manyosiris/events` | deny | 403 | yes | PASS |
| 15 | saas-signed-events | `saas-api.localhost` | `POST //api/channels/manyosiris/events` | deny | 403 | yes | PASS |
| 16 | saas-signed-events | `saas-api.localhost` | `POST /api/%63hannels/manyosiris/events` | deny | 403 | yes | PASS |
| 17 | saas-signed-events | `saas-api.localhost` | `POST /api/channels/%6danyosiris/events` | deny | 403 | yes | PASS |
| 18 | saas-signed-events | `saas-api.localhost` | `POST /api/channels/%6Danyosiris/%65vents` | deny | 403 | yes | PASS |
| 19 | saas-signed-events | `saas-api.localhost` | `POST /api/channels/../channels/manyosiris/events` | deny | 403 | yes | PASS |
| 20 | saas-signed-events | `saas-api.localhost` | `POST /api/./channels/manyosiris/events` | deny | 403 | yes | PASS |
| 21 | saas-signed-events | `saas-api.localhost` | `POST /api/channels/manyosiris/events/` | deny | 403 | yes | PASS |
| 22 | saas-signed-events-unreached | `saas-api.localhost` | `POST /api/channels%2fmanyosiris%2fevents` | deny_or_unreached | 403 | yes | PASS |
| 23 | saas-signed-events | `saas.localhost` | `POST /api/channels/manyosiris/events` | deny | 403 | yes | PASS |
| 24 | saas-signed-events | `saas.localhost` | `POST //api/channels/manyosiris/events` | deny | 403 | yes | PASS |
| 25 | saas-signed-events | `saas.localhost` | `POST /api/%63hannels/manyosiris/events` | deny | 403 | yes | PASS |
| 26 | saas-signed-events | `saas.localhost` | `POST /api/channels/%6danyosiris/events` | deny | 403 | yes | PASS |
| 27 | saas-signed-events | `saas.localhost` | `POST /api/channels/%6Danyosiris/%65vents` | deny | 403 | yes | PASS |
| 28 | saas-signed-events | `saas.localhost` | `POST /api/channels/../channels/manyosiris/events` | deny | 403 | yes | PASS |
| 29 | saas-signed-events | `saas.localhost` | `POST /api/./channels/manyosiris/events` | deny | 403 | yes | PASS |
| 30 | saas-signed-events | `saas.localhost` | `POST /api/channels/manyosiris/events/` | deny | 403 | yes | PASS |
| 31 | saas-signed-events-unreached | `saas.localhost` | `POST /api/channels%2fmanyosiris%2fevents` | deny_or_unreached | 403 | yes | PASS |
| 32 | many-admin-not-shadowed | `localhost` | `GET /instagram/accounts/420fedaa-a836-41c5-a6a1-99918dd85735/saas-delegation` | app_401_403 | 401 | no | PASS |
| 33 | many-admin-not-shadowed | `localhost` | `GET /api/instagram/accounts/420fedaa-a836-41c5-a6a1-99918dd85735/saas-delegation` | app_401_403 | 401 | no | PASS |
| 34 | many-admin-not-shadowed | `localhost` | `GET /api/whatsapp/accounts/420fedaa-a836-41c5-a6a1-99918dd85735/saas-delegation` | app_401_403 | 401 | no | PASS |
| 35 | many-admin-not-shadowed | `localhost` | `GET /api/facebook/accounts/420fedaa-a836-41c5-a6a1-99918dd85735/saas-delegation` | app_401_403 | 401 | no | PASS |
| 36 | saas-admin-not-shadowed | `saas-api.localhost` | `GET /api/v1/platform/channel-connections` | app_401_403 | 401 | no | PASS |
| 37 | saas-admin-via-web-not-shadowed | `saas.localhost` | `GET /api/v1/platform/channel-connections` | app_401_403 | 401 | no | PASS |
| 38 | many-health | `localhost` | `GET /health` | ok | 200 | no | PASS |
| 39 | many-dashboard | `localhost` | `GET /` | ok | 307 | no | PASS |
| 40 | saas-api-ready | `saas-api.localhost` | `GET /ready` | ok | 200 | no | PASS |
| 41 | saas-web | `saas.localhost` | `GET /` | ok | 200 | no | PASS |

Proof that denied requests never reached the apps (access logs of this run): saas-api received `POST /api/channels/manyosiris/events` only from many-worker (all 9 requests); many-api received `POST /api/saas/messages` only from saas-worker (3). What nginx (the only proxy) forwarded to many-api and saas-api: `/health`, 6 `POST /webhooks/meta`, the admin routes `GET /instagram|whatsapp|facebook/accounts/<uuid>/saas-delegation` (401), `GET /ready`, `GET /api/v1/platform/channel-connections` (401), and `POST /%2573aas/messages` (404, an escaped spelling that does not normalise to the signed prefix). 29 requests were answered 403 by nginx itself.

### 4.5 End-of-2b gate (local; allowlist empty; WSL no-egress netns; `_test` DB names)
- Many full suite: **1084 passed, 0 failed, 0 skipped** (1007 baseline + 77 policy tests). A first attempt skipped 638 tests because the unix-socket bridge had gone stale after a WSL restart; that was a harness fault and the run was repeated.
- SaaS full suite (`saas_p2_gate2b_test`): **1293 passed, 0 failed, 0 skipped** in 1910 s (1216 + 77 policy tests).
- `check_policy_copies.py` OK; Many-root and SaaS-root `check_contract_copies.py` OK; no migration file changed since main.
- GitHub Actions is paused for billing, so every gate here is local.

