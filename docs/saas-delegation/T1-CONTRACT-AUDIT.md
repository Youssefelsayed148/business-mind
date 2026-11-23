# T1 contract audit — 2026-10-28

Source: clean local checkout `../SAAS-chats-ai-phase6`, branch `feature/phase-6-channels`, HEAD `5fa72f7165ea0fc1dacd659e03e211341334ab32`. Each of the three source files was checked against its committed Git blob before copying. The SaaS checkout was read only. No application code or test source changed.

## Copy verification

`python docs/saas-delegation/t1-evidence/sync_contract.py` exited 0. CRLF is normalized to LF for comparison and hashing; no other bytes are ignored. Each diff was empty:

```text
LF-normalized diff: docs/saas-delegation/CONTRACT-V1.md
BEGIN DIFF
END DIFF
LF-normalized diff: docs/saas-delegation/CONTRACT-V1.1-DELTA.md
BEGIN DIFF
END DIFF
LF-normalized diff: backend/tests/fixtures/contract/signing_vectors.json
BEGIN DIFF
END DIFF
```

The three digests and requested source note are in [CONTRACT.sha256](CONTRACT.sha256:1). The fixture's non-name vector data was also asserted equal to the old fixture. Test IDs derive directly from `v["name"]` at `backend/tests/test_saas_contract_vectors.py:37`; the two new IDs (`arabic-and-symbol-body`, `empty-body`) passed without changing that file.

## Clause-by-clause review

This is a static review of Many's implementation against the newly copied clauses. The two requested test modules verify signing and existing payload rules; they do not establish every runtime behavior below. Separate runtime coverage, production proxy behavior, and real integration are **UNVERIFIED** in T1.

| Clause | Ownership and finding | Many evidence |
| --- | --- | --- |
| Section 4.1 origin caps; A14 origin field selection | Many's production `_origin()` emits only `type`, `campaign_name`, `opening_message_text`, `campaign_ref`, with caps 120/2000/128. The public builder passes `origin` through, but the production caller uses `_origin()`. Origin provenance has a gap; see proposed T1-P3. | `backend/app/services/saas_inbound.py:73`, `:96`, `:142`, `:203` |
| Section 4.1 / A14 signed 422 for invalid origin | SaaS receiver owns validation/rejection. Many makes 422 permanent via its non-retryable response branch. | `backend/app/services/saas_forwarder.py:342` |
| Section 4.1 stores origin once, displays it, fences/caps opening context to 500 | SaaS inbox and bot behavior; Many does not implement it and needs no equivalent. Many must send the bounded origin fields. | `docs/saas-delegation/CONTRACT-V1.md:47`; Many producer `backend/app/services/saas_inbound.py:96` |
| A14 retention and duplicate 202 | `channel_events.payload`, tenant cutoff, 30-day dedupe and `202 duplicate` belong to the SaaS event receiver. Many's outbox is `saas_forward_events`, a different table with its own policy; it is not required to implement SaaS tenant retention. | `docs/saas-delegation/CONTRACT-V1.1-DELTA.md:35`; `backend/app/models/saas_forward_event.py:20`; `backend/app/services/saas_forwarder.py:187` |
| A14 no compression of Many's 202 | Both nginx SaaS prefixes disable gzip. FastAPI installs CORS, no compression middleware; the checked-in Traefik API router has only prefix stripping. Runtime behavior of any upstream deployment proxy remains **UNVERIFIED**. | `nginx/default.conf:62`, `:67`; `backend/app/main.py:51`; `docker-compose.traefik.yml:24`; `backend/app/api/routes_saas_messages.py:106` |
| A14 SaaS honors Many Retry-After up to 300 s | SaaS sender behavior, not a 300-second cap on Many's event forwarder. No Many change required by this clause. The forwarder's separate section 6 gap is T1-P2. | `docs/saas-delegation/CONTRACT-V1.1-DELTA.md:37` |
| A14 compressed response decoding / 64 KB response and health caps | SaaS HTTP client owns decoding/capping. Many returns a small `id` response and a health object with a fixed status/detail and timestamps, not an unbounded payload. | `backend/app/api/routes_saas_messages.py:106`, `:134`; `backend/app/services/saas_health.py:63`, `:94` |
| A14 future status/pull times count as now; received_at clamp | SaaS receiver/poller owns these clamps. Many serializes UTC timestamps; no corresponding Many receiver exists for these event types. | `docs/saas-delegation/CONTRACT-V1.1-DELTA.md:38`; `backend/app/services/saas_health.py:103`; `backend/app/services/saas_inbound.py:147` |
| A14 SaaS-local delivery codes | These codes are outside Many's error enum. Many's mapping emits its contract codes, not `many_auth_rejected` or the other SaaS-local labels. | `backend/app/services/saas_error_mapping.py:19`, `:80`; `backend/app/services/saas_outbound.py:31` |
| A14 second rotation replaces original immediately | Implemented: current becomes previous on each rotation; previous has a 24-hour expiry; only current and previous are accepted. Outbound signing uses current. | `backend/app/services/saas_delegation_service.py:116`, `:127`; `backend/app/api/routes_saas_messages.py:61`; `backend/app/services/saas_forwarder.py:310`, `:320` |
| A14 receiver lookup before throttle; migrations 0023/0024 rollback limitation | Descriptions of the SaaS route/schema. No Many implementation is needed, and Many migrations must not be altered to imitate them. | `docs/saas-delegation/CONTRACT-V1.1-DELTA.md:41` |
| A15 SaaS-to-Many 401 retry, six attempts, remembered auth rejection, resend resets memory | Entirely SaaS sender behavior. **401 followed by timeouts still labels `many_auth_rejected` is SaaS-side only; no Many change is needed.** Many provides generic 401 responses. Its event forwarder's later timeout may set `retrying`; the contract does not require it to remember the SaaS sender's error label. | `docs/saas-delegation/CONTRACT-V1.1-DELTA.md:44`; `backend/app/api/routes_saas_messages.py:45`; `backend/app/services/saas_forwarder.py:324` |
| A15 Many-to-SaaS 401 retry | Implemented with payload retained, ordinary backoff and degraded/auth_rejected status. Retry expiration has the section 6 gap T1-P1. Other 4xx are terminal. | `backend/app/services/saas_forwarder.py:338`, `:342`, `:353`, `:361`; payload retention `:130` |
| A15 rotation runbook | Operational SaaS pause → rotate → update Many → resume. Many already accepts the new secret while retaining the previous one. No network action taken. Runbook execution **UNVERIFIED**. | `docs/saas-delegation/CONTRACT-V1.1-DELTA.md:46`; `backend/app/services/saas_delegation_service.py:116` |
| Section 6 Many network/5xx/429/401 retries; other 4xx permanent | Implemented by the HTTPError/status branches. Same row/event_id is reused; attempts re-sign with the current secret. Retry-After is partial (T1-P2). | `backend/app/services/saas_forwarder.py:319`, `:325`, `:335`, `:338`, `:342` |
| Section 6 exponential jitter / degraded health / no AI fallback | Backoff uses exponential growth with jitter; retry records `saas_degraded=True`. The forwarder queues/fails rather than calling AI. This flag is Many's forward health, separate from derived Meta health. | `backend/app/services/saas_forwarder.py:223`, `:248`, `:361`; `backend/app/services/saas_health.py:63` |
| Section 6 / A7 24-hour limit and ordered queue | Pending rows are processed in seq order and a retry blocks later rows. Expiration is not enforced before sending/waiting (T1-P1). | `backend/app/services/saas_forwarder.py:255`, `:274`, `:279`, `:353` |
| Section 6 SaaS-to-Many timeouts, redirects, backoff, same message_id, failure codes, health recovery (ADR-020), asynchronous customer delivery | SaaS sender/job/health behavior. Many accepts asynchronously, dedupes by connection/message id, and queues status events; it does not implement SaaS's retry-budget health policy. A15 supersedes the generic many_unreachable label when a 401 was observed. | `docs/saas-delegation/CONTRACT-V1.md:77`; `backend/app/api/routes_saas_messages.py:104`; `backend/app/services/saas_outbound.py:133`; `backend/app/services/saas_status.py:44` |
| Section 7 retention/privacy | Tenant `channel_events` retention/export/deletion and contact identity rules are SaaS-side. Many does not mirror those tables or tenant cutoffs. Many clears sent/dropped payloads immediately, failed payloads after 7 days, terminal event rows after 30 days, outbound idempotency rows after 30 days (>=7-day minimum). The sweep is daily. Reviewed delegation logs contain identifiers/status or generic errors, not message bodies. | `docs/saas-delegation/CONTRACT-V1.md:83`; `backend/app/services/saas_forwarder.py:130`, `:187`, `:347`; `backend/app/workers/saas_beat_schedule.py:18`; `backend/app/api/routes_saas_messages.py:45` |

## Proposed tickets only — no implementation in T1

1. **T1-P1 — enforce the 24-hour deadline before another HTTP attempt or queue wait.** Section 6 (`CONTRACT-V1.md:76`) and A7/A15 bound retries to 24 hours. `_attempt()` sends first (`backend/app/services/saas_forwarder.py:326`), accepts success immediately (`:331`), and checks age only after a retryable failure (`:353`). An expired row can therefore still be delivered; `next_attempt_at` is also checked before expiry (`:279`) and a new delay is not bounded to the remaining budget (`:359`), delaying failure/queue release. Proposed fix: expire before send/wait, cap scheduling at the deadline, then continue the ordered queue. Runtime reproduction/new tests **UNVERIFIED**, not run in T1.
2. **T1-P2 — complete Retry-After handling.** Section 6 (`CONTRACT-V1.md:76`) says honor Retry-After. `_retry_after()` parses only numeric seconds and caps them to one hour (`backend/app/services/saas_forwarder.py:230`); an HTTP-date is ignored, and a numeric delay over one hour can be retried too early. The header is consulted only for 429, not 503 (`:337`). Proposed fix: support seconds and HTTP-date; honor the supplied delay within the remaining 24-hour budget and avoid retrying before it. The contract's separate 300-second cap is explicitly for the **SaaS sender**, not this path. Runtime reproduction/new tests **UNVERIFIED**, not run in T1.
3. **T1-P3 — select the delivered campaign opening for origin.** Section 4.1 (`CONTRACT-V1.md:47`) and A11 (`CONTRACT-V1.1-DELTA.md:28`) describe campaign-origin conversations and the opening text Many delivered. `_origin()` queries outbound campaign messages without a sent/delivered/read status filter, orders newest first (Instagram first prefers final_delivery), and does not anchor the selection to the conversation's opening (`backend/app/services/saas_inbound.py:73`). A queued/failed or later campaign message can supply the origin. Proposed fix: resolve the actual delivered campaign opening deterministically while retaining the existing caps and sending it on each relevant inbound. Runtime reproduction/new tests **UNVERIFIED**, not run in T1.

These are static code/contract gaps, not failures of the 18 requested tests. No application fixes, new ticket execution, commit, push, deployment, Docker command, or real Meta/OpenAI/SaaS request occurred. Facebook/Instagram disconnected-account blocking remains unchanged per the owner decision; error-table verification and credential files remain outside T1.

## Test evidence

Exact command in the isolated snapshot, with private Redis flushed before each attempt:

```bash
APP_ENV=test TEST_DATABASE_URL="$TEST_DATABASE_URL" pytest tests/test_saas_contract_vectors.py tests/test_saas_signing.py -v --junitxml="$evidence/tests.xml"
```

`TEST_DATABASE_URL=postgresql+psycopg://postgres@/many_test?host=/var/tmp/many-t0-20261028/socket&port=55432`. The cluster has no TCP listener. A fresh network namespace exposes loopback only; Redis is local to that namespace. No `.env` file is present in the snapshot. An initial attempt with DATABASE_URL unset exited 4 before collection because Settings requires it; retained as `t1-evidence/tests-attempt-1.log`. The successful attempt supplied `postgresql+psycopg://unused.invalid/many_test` solely as an unreachable required-setting sentinel and asserted conftest selected the explicit TEST_DATABASE_URL. Result: **18 passed, 0 skipped in 0.35s**, exit 0. Both attempts stopped PostgreSQL and their private Redis on exit. See [test log](t1-evidence/tests.log:1) and [JUnit XML](t1-evidence/tests.xml:1). Lint/type checks, deployment verification, and broader suites **UNVERIFIED** in this documentation/fixture-only ticket.
