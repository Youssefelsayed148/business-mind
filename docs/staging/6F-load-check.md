# 6F: Load check

Status: **scripts written; unit tests run (statistics, safety checks, and one run against a local fake server). Nothing was run against Many, the SaaS API or staging.** Targets are **empty on purpose**: decision D3 (peak webhooks per second, dashboard users) is pending because the owner has not supplied today's peak traffic. I do not invent targets. Exit criterion (`docs/PHASE-6-PLAN.md`): numbers recorded against stated targets.

## Rules

- Staging only, throwaway data only. Never run any of this against a live Many, live SaaS or live Meta endpoint.
- Run a backup first (`scripts/ops/backup_all.sh`, 6C). Webhook bursts create leads, messages and logs.
- Start small (the first run of each tool: low count or low concurrency and short duration), look at the health and logs, then raise it. Stop at the first 5xx burst you did not expect.
- No real Meta or OpenAI calls. The webhook script sends signed mock Instagram events to the URL you give it; point it at the **staging** Many only. Because it exercises the frozen Instagram receive path, nothing is edited; if it fails in a way that looks like a code fault, stop and report.
- Never paste the app secret or the session cookie into chat, tickets or this file.

## A. Webhook burst (existing script)

Tool: `scripts/send_rehearsal_webhooks.py` (documented in `docs/rehearsal-testing.md` section 3). It reads `META_APP_SECRET` from a `.env` file in the current directory (it does not print it), signs each mock event, and sends them one after the other with a summary of 200s, 429s, failures and average response time.

Facts from the script and guide:
- It is sequential (one request at a time): it measures what one sender can do, not a parallel burst. For a parallel burst run several copies in separate shells. Read in `nginx/unified.conf`: `/webhooks/meta` has a per-source-IP limit of 10 requests/s with burst 20 (`limit_req zone=meta_webhook burst=20 nodelay`); no `limit_req_status` is set there, so nginx's default rejection status (503, not 429) is expected above the limit. **UNVERIFIED** until run; the script counts only 429 as "rate limited", so a 503 shows up under "Failed (non-200)". One sender from one IP is therefore capped near the zone limit: a high rate test needs the limit understood first, and the staging edge may sit behind another proxy that changes the key.
- It uses demo account ids (`178400000000001` to `...010`) from the rehearsal seed (`python -m app.scripts.seed_rehearsal`). **UNVERIFIED** whether the seed may run with the staging `APP_ENV` (the guide shows `APP_ENV=development`). Without the seed accounts the events are accepted at the edge but match nothing, which tests the receive path only.
- The `.env` it reads must hold the staging app secret for this run only (host-only, mode 600, not in git).

Commands (from the repository root; replace the URL with the staging Many webhook URL):

```sh
python3 scripts/send_rehearsal_webhooks.py --count 20 --verbose --url https://MANY_HOST/webhooks/meta
python3 scripts/send_rehearsal_webhooks.py --count 100 --url https://MANY_HOST/webhooks/meta
python3 scripts/send_rehearsal_webhooks.py --count 300 --mode mixed --url https://MANY_HOST/webhooks/meta
python3 scripts/send_rehearsal_webhooks.py --count 50 --repeat-same-event 50 --url https://MANY_HOST/webhooks/meta   # duplicate protection check
```

While it runs, in another shell watch `docker compose ... logs -f many-api many-worker` and `docker stats` (CPU, memory), and note the worker queue length with the same command used for the alerts queue check (6D). Record the script's summary block as printed.

## B. SaaS API load (new script)

Tool: `scripts/ops/load_saas_api.py` (stdlib only). GET requests only, fixed concurrency and duration, prints a table with requests, errors, error rate, requests/s and p50/p95/p99 per path and in total.

- Refuses any host that does not look like staging (loopback, or a host name label `staging`/`stg`) unless `--i-know-this-is-staging`. Hard caps: concurrency 100, duration 300 s.
- Unauthenticated mix (default): `/health`, `/ready`, `/api/v1/auth/config`. **UNVERIFIED** that the staging edge exposes `/ready` and `/api/v1/auth/config` on the SaaS API host; override with `--path` (repeatable).
- Authenticated mix (`--auth`): a session cookie in the environment variable `LOAD_SESSION_COOKIE` (value only, or `name=value`; default cookie name `chatbot_session`). Use a throwaway staging user, log in in a browser, copy the cookie value from the developer tools, export it in your shell, and clear it afterwards. The script never prints it and aborts if the first authenticated request is not 2xx. With `--tenant-id` the mix adds the tenant's contacts list, inbox and inbox counts (all GET). **UNVERIFIED** against a running API: the paths come from the router prefixes in the code; the unit test only uses a fake server.
- The cookie is the user's real session: the load runs with that user's rights, read-only calls only.

Commands (replace the placeholders):

```sh
# small first
python3 scripts/ops/load_saas_api.py --base-url https://SAAS_API_HOST --concurrency 2 --duration 15
# unauthenticated mix, realistic size
python3 scripts/ops/load_saas_api.py --base-url https://SAAS_API_HOST --concurrency 10 --duration 60
# authenticated mix
export LOAD_SESSION_COOKIE='<value from the browser>'
python3 scripts/ops/load_saas_api.py --base-url https://SAAS_API_HOST --concurrency 10 --duration 60 --auth --tenant-id TENANT_UUID
unset LOAD_SESSION_COOKIE
```

Rate limits: the SaaS edge and API may answer 429 above their limits (`docs/rate-limiting.md` has the zones; read it before choosing concurrency). A 429 counts as an error in this script's table. Record which paths returned them. Do not raise the limits to make a run look better.

## C. Targets (EMPTY: the owner supplies them)

Decision D3: today's real peak traffic times 3 is the recommended starting point. Fill the Source column with where the number came from. Until a row has a target, its result is recorded without a pass/fail.

| Metric | Target | Source of the number | Measured | Pass / fail |
|---|---|---|---|---|
| Meta webhooks per second (peak) | | | | |
| Webhook success rate (200 share) | | | | |
| Webhook average response time (ms) | | | | |
| Dashboard concurrent users | | | | |
| SaaS API p95 latency, unauthenticated mix (ms) | | | | |
| SaaS API p95 latency, authenticated mix (ms) | | | | |
| SaaS API p99 latency (ms) | | | | |
| SaaS API error rate (%) | | | | |
| Worker queue length after the burst drains within (minutes) | | | | |
| CPU / memory ceiling on the staging host | | | | |

## D. Result template

```
Date (UTC):
Staging commit:
Host size (CPU, RAM):
Backup taken before (folder name):

A. Webhook burst
  command:
  summary block (copy as printed):
  rate-limited (429) count:
  queue length at end / time to drain:
  notable log lines (sanitized):

B. SaaS API load
  command (cookie not included):
  table (copy as printed):
  paths with errors and the status seen:

Host: peak CPU %, peak memory, disk change:
Anything unexpected:
```

| Run | Tool and parameters | Result (owner fills in) |
|---|---|---|
| A1 | webhook script, count 20 verbose | |
| A2 | webhook script, count 100 | |
| A3 | webhook script, count 300 mixed | |
| A4 | duplicate protection, 50 repeats | |
| B1 | SaaS script, c=2 15 s | |
| B2 | SaaS script, c=10 60 s unauthenticated | |
| B3 | SaaS script, c=10 60 s authenticated | |

## What I ran here

`python3 scripts/ops/test_load_saas_api.py` (14 tests: percentile and summary maths, staging-host refusal, caps, cookie handling, a run against a fake server on loopback). Nothing else. The webhook script was read, not run.
