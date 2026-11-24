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
