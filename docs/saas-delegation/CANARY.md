# Staging WhatsApp delegation canary

This is an operator runbook, not a record of a completed canary. All live checks
below are **UNVERIFIED** until the operator records evidence. Use one free Meta
app WhatsApp **TEST number**, only recipients verified/allow-listed for that
number, and synthetic messages. Do not connect a customer/production number,
run outreach/campaigns, or send to other recipients. Deployments and live sends
require the owner's approval; no deployment or network call was made for T6.

## Preconditions and migration decision

- Many `feature/saas-delegation` (record the deployed SHA, at least `1891f89`)
  must already be deployed to **staging**. API, worker and exactly **one beat
  process** must run the same source/configuration. Redis must be reachable by
  those processes. Do not flush a staging/shared Redis; flushing is for the
  isolated test harness only.
- SaaS `feature/phase-6-channels`, frozen source SHA `5fa72f7`, must already be
  deployed to a public HTTPS domain, with its channel worker/poller running.
  Do not edit its repository. Many must have a public HTTPS callback address
  reachable by SaaS. In Many production mode (`APP_ENV`), SaaS base URLs must
  use HTTPS and must not be private/loopback/link-local hosts, including DNS
  answers. Do not weaken validation to use a private staging hostname.
- Meta test-number webhook subscription, signature verification, account/token
  connection and allow-listed recipient must be ready. Verify connected state
  without displaying token values. Temporary test-token expiry can yield
  `token_expiring` instead of `connected`; record this and refresh through the
  approved connection flow before calling the connected-health check a pass.
- Keep Many's own AI disabled on this test account before enabling delegation
  and through rollback. Configure the SaaS canary bot/inbox in advance; live
  bot checks may incur provider usage and belong to the approved operator run.

From the deployed **backend directory**, using its securely provisioned staging
environment (do not open env files or echo credentials), run:

```sh
alembic current
alembic heads
```

Record which case applies **before** upgrading:

| Observed `alembic current` | Decision and expected result |
| --- | --- |
| `0022_whatsapp_opt_in` on the existing staging schema | Supported canary starting point. With migration approval, `alembic upgrade head` applies 0023–0027; `alembic current` must then report `0027_saas_conn_id_lowercase (head)` at this source revision. |
| Already `0027_saas_conn_id_lowercase (head)` | No upgrade needed. Confirm the source has one head and 0023–0027 are ancestors; preflight checks both. |
| No revision / truly empty disposable DB | A2 repaired migration 0019 and rehearsed empty?head, 0022?head and downgrade/upgrade. Use Alembic only; no stamp/create_all shortcut. Production bootstrap and schema state still require separate approval and inspection. |
| Other revision, multiple heads, missing tables, or drift | Stop and investigate; a version marker alone does not prove schema integrity. |

T6 inspected source only; no staging DB was accessed. **Applicable staging case:
UNVERIFIED — operator must select and record the actual `alembic current`
result.** A2 disposable tests now prove empty?head and 0022?head after the 0019 repair
(see `a2-a4-evidence/WORKER-REPORT.md`); they are not evidence of the staging
schema. Earlier T6 evidence of an empty-DB 0019 failure is historical and was
resolved locally by A2. If a newer source adds migrations, use that source's single
head and retain 0023–0027 in its ancestry.

## Setup order

1. In SaaS, pause channel sending/provisioning before setup. If the connection
   does not exist yet, create it in a paused state (or pause it immediately
   before linking Many); keep it paused throughout credential entry.
2. Create the WhatsApp connection in SaaS for this single canary number. Set
   its Many target to the public HTTPS staging Many domain, according to the
   SaaS connection form.
3. Copy the connection UUID in canonical **lowercase, hyphenated** spelling
   and its shared secret directly between authorized settings forms. The
   secret must have at least 32 characters, with no surrounding whitespace.
   Never paste it into this document, shell arguments, logs or screenshots.
4. As a Many owner/admin, open this WhatsApp account's **SaaS delegation**
   settings. Enter that UUID, the secret, and the SaaS public HTTPS base URL
   (domain/base only, not the events endpoint). Enable delegation and save.
   Confirm the configured UUID matches the SaaS connection exactly. No
   undocumented environment variable replaces these per-account DB settings.
5. Run preflight below. Confirm the test account is connected and no unrelated
   account uses this connection. Resume the connection in SaaS only after both
   sides match and the checks pass.

## Offline readiness check

From the Many repository root in the backend Python environment:

```sh
python scripts/canary_preflight.py --static-only
```

Expected: three static PASS lines, one database UNVERIFIED line, **exit 2**.
This does not mean staging is ready. It does not import app settings, load env
files, resolve hosts, contact HTTP services or connect to Redis.

For the DB checks, run on the staging DB host with an approved **read-only** DB
identity and a local PostgreSQL Unix socket. Securely provision the dedicated
`CANARY_DATABASE_URL` variable without displaying it. The script accepts only
`postgresql+psycopg` URLs with one absolute Unix-socket `host` query parameter
and optional `port`; it refuses TCP/DNS targets and never falls back to
`DATABASE_URL`. It uses existing backend SQLAlchemy/psycopg dependencies, no new
packages. Supply the **Many WhatsApp account UUID**, not the SaaS connection id:

```sh
python scripts/canary_preflight.py --account-id <MANY_WHATSAPP_ACCOUNT_UUID> --beat-process-count 1
```

Supply `--beat-process-count 1` only after independently observing exactly one
running beat process across the deployment. This is operator evidence, not a
process discovered by the script. Missing, zero or multiple beats fail readiness.

Expected: all five PASS lines, **exit 0**. Any failure exits **1**, without
printing a DB URL, exception traceback, stored UUID or secret. The DB transaction
is read-only, with connect/statement timeouts. It selects the Alembic version and the chosen account's connection UUID,
delegation-enabled flag and base URL, plus a database-computed Boolean for
secret presence. It never fetches token or secret ciphertext. It requires enabled
delegation, a public HTTPS URL by syntax (DNS remains unverified), and a stored
secret. In `APP_ENV=test`, only `many_test` or `many_test_<worker>` names are
permitted. For
local validation explicitly set `TEST_DATABASE_URL` and use:

```sh
python scripts/canary_preflight.py --database-url-env TEST_DATABASE_URL --account-id <DISPOSABLE_ACCOUNT_UUID> --beat-process-count 1
```

`--nginx-config <PATH>` can inspect the deployed standalone nginx config instead
of the repository default. The static checks verify a single source migration
head with the SaaS ancestry, one merged source beat schedule containing each
of the four SaaS tasks once, and explicit `gzip off` in both signed prefixes.
They do **not** prove one running beat instance, worker registration/liveness,
loaded nginx includes, proxy overrides or HTTP reachability. Independently
confirm those on staging. If staging uses Traefik, the nginx PASS is a source
check only: verify that the actual ingress/Dokploy layer has no compression
on `/api/saas` and does not rewrite/signature-modify the body. See
[KNOWN-LIMITS.md](KNOWN-LIMITS.md).

## Live acceptance checks — operator only

Record UTC timestamps, deployed SHAs, opaque connection/conversation/message
ids and sanitized outcomes. Never record recipient phone numbers, message
content, tokens, shared secrets, authorization/signature headers or complete
webhook bodies. A `202` means accepted by Many, **not sent**; require the status
callback/recipient evidence below. Do not mark a check passed from queueing alone.

| Check | Action | Expected result / evidence |
| --- | --- | --- |
| (a) Customer → bot | From the allow-listed handset, send a synthetic text to the Meta test number. | One inbound message in SaaS, stable Many conversation id, one bot answer received on the handset; no Many AI answer. Many forward status succeeds and pending queue drains. |
| (b) Human handoff | Use the canary bot's configured handoff trigger or SaaS inbox handoff action. Send another test message after handoff. | SaaS marks the conversation waiting for/assigned to a human; automatic bot replies stop. Many continues forwarding genuine inbound messages. Handoff is controlled in SaaS. |
| (c) Agent → WhatsApp | From that SaaS inbox conversation, send one synthetic agent reply while the window is open. | Many accepts it, then reports `sent`; the allow-listed handset receives the reply once. Record SaaS message id and Many id. |
| (d) Delivery status | Observe the reply on the connected handset; open it if read receipts are enabled. | SaaS shows `sent`, then `delivered` from the real WhatsApp status webhook. `read` is optional if receipts are disabled. No status for 15 minutes yields `unconfirmed` and is not a pass. |
| (e) Many Take Over guard | Open the same conversation in Many and inspect Take Over / Resume Bot. If testing the route, use the authenticated owner/admin session. | UI indicates “Managed in the SaaS inbox”; Take Over cannot switch control. POST `/conversations/{id}/take-over` returns 409 with detail code `CHANNEL_MANAGED_BY_SAAS` (external proxy may prefix `/api`). Resume Bot is guarded too. |
| (f) Health | Observe SaaS channel health after resume and its next successful signed health poll (normally within 5 minutes). | `connected`, refreshed `checked_at`; no auth-rejected/degraded state. Push transitions and heartbeat also arrive. Shared provider-wide webhook failures can degrade all channels; investigate rather than treating a source preflight PASS as live health. |
| (g) Closed window | Stop inbound messages from the test handset. After **more than 24 h since its last inbound**, ensure there is no open free-entry-point window; send one plain-text agent reply from SaaS, without a template. | Send is rejected with `message.status` failed / `window_closed`; no handset delivery. Record actual source of rejection and actual Meta numeric code/subcode **only if Meta returned one**, as explained below. |

For (g), ordinary direct handset messages avoid the click-to-WhatsApp free-entry
window. Do not alter DB timestamps, bypass the window guard or renew the window
with a new customer message to manufacture the result. If SaaS itself blocks
the send before Many accepts it, record that separately: it does not demonstrate
Many's callback behavior.

**Current Many limitation for the requested real Meta code:**
`backend/app/services/saas_outbound.py:268-269` returns `window_closed` locally,
before `_send_with_rate_limit_retries` at line 271. Thus the expected expired
window result has **no Meta request and no numeric Meta error**. Record
`N/A — Many local window guard, no Meta call` when that is what happened.
The mapping table's `131047` is an expected mapping, not an observed result.
If a real Meta rejection occurs naturally (for example a boundary/state race),
record its actual numeric code/subcode from sanitized structured evidence;
do not invent a value or disable enforcement to obtain it. Capturing a real
numeric code in the normal locally blocked case remains **UNVERIFIED / not
observable through this path**.

## Rollback

1. Turn **delegation off in Many** for this test WhatsApp account; save and
   confirm it is off. A13 drops queued, unsent SaaS forward events, rather than
   replaying them after the switch. Check pending forward count/status and
   dropped-event logs; an already sent/in-flight event cannot be recalled.
2. **Pause the connection in SaaS.** Do not revoke/delete the connection as a
   substitute for pausing. Leave Many AI disabled so rollback does not start
   unintended replies. Already accepted outbound sends also check delegation
   before sending and fail if it is off.
3. Record rollback time and sanitized results. Do not downgrade schema, delete
   conversations or replay dropped events. If continuing later, recheck both
   configurations and expiry, then repeat the pause/link/resume order.

## Many environment checklist — names only

Core runtime (API, worker and beat must share the required configuration):

- [ ] `APP_ENV`
- [ ] `DATABASE_URL`
- [ ] `REDIS_URL`
- [ ] `TOKEN_ENCRYPTION_KEY`
- [ ] `APP_SECRET_KEY`
- [ ] `JWT_SECRET`
- [ ] `APP_BASE_URL`
- [ ] `DASHBOARD_BASE_URL`
- [ ] `FRONTEND_URL`
- [ ] `ALLOWED_ORIGINS`
- [ ] `META_APP_ID`
- [ ] `META_APP_SECRET`
- [ ] `FACEBOOK_APP_ID`
- [ ] `FACEBOOK_APP_SECRET`
- [ ] `META_WEBHOOK_VERIFY_TOKEN`
- [ ] `META_GRAPH_API_VERSION`
- [ ] `WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID` (if using Embedded Signup)
- [ ] `META_WEBHOOK_SECRET` (if this deployment uses the webhook-secret override)

Operator/local validation only:

- [ ] `CANARY_DATABASE_URL` (dedicated local read-only preflight target)
- [ ] `APP_ENV`
- [ ] `TEST_DATABASE_URL` (disposable tests only)
- [ ] `REDIS_URL` (private, flushed Redis for tests only)

Meta access tokens and SaaS connection UUID/base URL/shared secret live in the
authorized account configuration, not new delegation env variables. No Many
OpenAI key is needed for delegated replies. Do not open `dashboard/.env.local`
or the out-of-scope credential file while preparing this run.

## Operator evidence sheet

| Field | Observed result |
| --- | --- |
| Many / SaaS deployed SHA | UNVERIFIED |
| Meta TEST number and recipient allow-list checked (no values) | UNVERIFIED |
| Migration case selected / `alembic current` / single head | UNVERIFIED |
| Preflight command, time, exit and sanitized output | UNVERIFIED |
| One running beat / workers / actual ingress compression checked | UNVERIFIED |
| (a) through (f), timestamps and opaque message ids | UNVERIFIED |
| (g) last inbound UTC / send UTC / no free-entry window | UNVERIFIED |
| (g) `window_closed` callback / local versus Meta rejection | UNVERIFIED |
| (g) actual numeric Meta code/subcode, or N/A with reason | UNVERIFIED |
| Rollback completed / queues dropped / SaaS paused | UNVERIFIED |
