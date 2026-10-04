# Phase 7 verification report — 2026-10-04

Final full suite: **338 passed, exactly 23 pre-existing failures, 0 skipped** (361 tests). All **54 new tests passed**: 51 E2E/matrix tests and 3 architecture invariants. Baseline: 284 passed, 23 failed. The baseline and final failure-name sets match exactly, verified from JUnit XML. [Machine-readable verification](whatsapp-outreach-verification.json).

No commits or pushes were made. Existing staged Phase 5–6 work was preserved. No Instagram application code or tests were edited. Phase 7 changes remain unstaged.

## What ran

- Full pytest before changes and after fixes, in the existing backend Docker image (Python 3.11, pytest 9.1.1), with `APP_ENV=test`, `RATE_LIMIT_ENABLED=false`, and both `DATABASE_URL` and `TEST_DATABASE_URL` pointing to the disposable `whatsapp_phase7_tests` DB. The project's local Redis received `FLUSHALL` before each full run. Both URL overrides matter: concurrency and migration tests construct their own connections from `DATABASE_URL`.
- E2E tests used real PostgreSQL and Redis/Lua token buckets. Celery task deliveries used `.apply(..., throw=True)` eagerly; a captured broker queue preserved task identity and countdown for bounded manual draining. Meta HTTP was intercepted with `httpx.MockTransport` inside the actual WhatsApp messaging/management clients. No send, policy, claim, consent, template-sync or rollup service was mocked.
- Covered public unverified opt-in → configured keyword → STOP; duplicate inbound webhook; old/equal evidence ordering; evidence-free resubscribe rejection; template submit/sync, attested CSV import, campaign start/dispatch/rollup, cap usage and completion timestamps.
- Covered a frozen campaign audience containing opted-in, unknown, opted-out, legacy unattested and missing-variable contacts. Permanent refusals use the expected reason codes and increment skipped counters once across repeated task deliveries. Campaign start still freezes only eligible contacts; the mixed-delivery scenario represents eligibility changes or legacy rows after freezing rather than changing audience behavior.
- Covered RED quality, stale health, feature disabled, paused account and exhausted daily cap: pending state and bucket unchanged, no HTTP request, repeated dispatches coalesced. Covered health-unconfirmed resume, fresh health recovery and operator pause/resume.
- Covered 131048/131049 without retry, timeout/invalid JSON as unknown outcomes charged to the daily cap, a twice-run stale-send reaper, repeated task delivery, double-clicked start, and two independent worker sessions racing for a recipient or the final daily slot (one slot already used).
- Covered an access-token canary in logs, consent evidence, API responses, invalid-JSON bodies and echoed provider error messages. The AST invariants cover the sole production template sender, explicit authorization dependencies for every outreach route, and consent mutation/event ownership. Neutral contact construction with `marketing_consent='unknown'` is allowed.

## Bugs found and fixed

| Bug | Minimal fix |
| --- | --- |
| Public opt-in and inbound webhook handlers wrote consent events/state outside the consent service | Moved event creation and keyword consent transitions into `whatsapp_consent_service`; handlers delegate |
| A late JOIN webhook could undo STOP even when its provider timestamp was older or equal | Ignore keyword opt-in evidence at or before `opted_out_at`; a genuinely newer explicit keyword remains valid resubscribe evidence. STOP takes precedence when keywords overlap; imports and CTWA cannot undo opt-out |
| Outreach read/preview/health/stat routes accepted lower workspace roles | Restricted those route dependencies to owner/admin, without changing global permissions or Instagram routes |
| Public JWTs did not explicitly require an expiry claim | Added an explicit public capability permission dependency requiring `aud` and `exp`; anonymous requests still need no user bearer token |
| Blocked send tasks spent a token before checking account/consent/cap policy | Precheck policy before token acquisition; repeat the policy check inside the account-locked send reservation |
| Repeated dispatcher deliveries behind a defer gate queued a wake-up each time | Reused the existing Redis coalescing helper for gated dispatcher scheduling |
| 131048/131049 were blocked from task retry but their persisted Message remained `retryable=true` | Forced the stored and returned retryability false for both codes |
| Meta could echo the supplied token in error text, which was persisted or returned by management APIs | Redact the exact supplied token in template-send and management error messages |
| Operator/circuit-breaker campaign pauses had no account pause timestamp, making resume impossible even after a poll | For campaign-only pauses, use the campaign transition timestamp as the health confirmation boundary; account pauses still use their own pause timestamp |
| The account row lock reused a cached ORM object, permitting a send after another session committed a pause; cached consent could likewise bypass revocation | Reload the locked account and campaign/contact/template policy rows before reserving a send. A real two-session regression exercises both independently committed pause and opt-out |

Existing WhatsApp tests received three fixture corrections, without removing assertions: task tests explicitly enable outreach so their mocked-send scenarios reach the send path; the known-retryable service test uses 130429 instead of the permanently excluded 131048; the explicit resubscribe webhook now has a later provider timestamp than STOP. These tests all pass.

## Authorization matrix

Each row was exercised through FastAPI with real DB membership resolution, an admin global user role and the indicated workspace membership role. Member is not a supported stored role enum; its string falls back to viewer permissions and was explicitly tested. Operator was also explicitly tested. Other-workspace requests used an authorized owner membership there, proving resource hiding rather than membership denial.

All paths below start with `/whatsapp`. The other-workspace column includes path IDs and, for collection/import/create routes, account/template IDs supplied via query/body/form.

| Route | Owner | Admin | Member / operator | Viewer | Other workspace |
| --- | --- | --- | --- | --- | --- |
| GET `/contacts` | 200 | 200 | 403 | 403 | 404 |
| GET `/contacts/{id}` | 200 | 200 | 403 | 403 | 404 |
| POST `/contacts/import` | 201 | 201 | 403 | 403 | 404 |
| POST `/contacts/{id}/grant` | 200 | 200 | 403 | 403 | 404 |
| POST `/contacts/{id}/revoke` | 200 | 200 | 403 | 403 | 404 |
| GET `/templates` | 200 | 200 | 403 | 403 | 404 |
| POST `/templates` | 201 | 201 | 403 | 403 | 404 |
| GET `/templates/{id}` | 200 | 200 | 403 | 403 | 404 |
| PATCH `/templates/{id}` | 200 | 200 | 403 | 403 | 404 |
| DELETE `/templates/{id}` | 200 | 200 | 403 | 403 | 404 |
| POST `/templates/{id}/submit` | 200 | 200 | 403 | 403 | 404 |
| POST `/accounts/{id}/templates/sync` | 202 | 202 | 403 | 403 | 404 |
| POST `/templates/{id}/preview` | 200 | 200 | 403 | 403 | 404 |
| POST `/templates/{id}/test-send` | 200 | 200 | 403 | 403 | 404 |
| GET `/campaigns` | 200 | 200 | 403 | 403 | 404 |
| POST `/campaigns` | 201 | 201 | 403 | 403 | 404 |
| GET `/campaigns/{id}` | 200 | 200 | 403 | 403 | 404 |
| PATCH `/campaigns/{id}` | 200 | 200 | 403 | 403 | 404 |
| POST `/campaigns/{id}/dry-run` | 200 | 200 | 403 | 403 | 404 |
| POST `/campaigns/{id}/start` | 202 | 202 | 403 | 403 | 404 |
| POST `/campaigns/{id}/pause` | 200 | 200 | 403 | 403 | 404 |
| POST `/campaigns/{id}/resume` | 200 | 200 | 403 | 403 | 404 |
| POST `/campaigns/{id}/cancel` | 200 | 200 | 403 | 403 | 404 |
| GET `/campaigns/{id}/stats` | 200 | 200 | 403 | 403 | 404 |
| GET `/accounts/{id}/outreach-health` | 200 | 200 | 403 | 403 | 404 |
| POST `/accounts/{id}/health-refresh` | 202 | 202 | 403 | 403 | 404 |
| PATCH `/accounts/{id}/outreach-settings` | 200 | 200 | 403 | 403 | 404 |
| POST `/accounts/{id}/opt-in-link` | 200 | 200 | 403 | 403 | 404 |
| POST `/public/whatsapp/opt-in/{token}` | 202 anonymously with valid token; 429 when limited | Same | Same | Same | Invalid capability / wrong audience / expired: 404 |

## Migration rehearsal

Ran `scripts/rehearse_whatsapp_migrations.ps1` without a snapshot against PostgreSQL **15.19**. It seeded **100 WhatsApp accounts, 100,000 leads and 300,000 legacy messages**, then executed upgrade head, five separate `downgrade -1` calls, and upgrade head again. [Full emitted SQL, schema checks, counts and timings](whatsapp-outreach-migration-rehearsal.json).

| Operation | Result | Elapsed |
| --- | --- | --- |
| Build/strip to genuine pre-outreach 0017 shape | Passed | 0.827 s for schema upgrade; seed time excluded |
| 0017 → 0022 | Passed; 100,000 contacts, all unknown | 43.690 s |
| 0022 → 0021 | Passed | 0.147 s |
| 0021 → 0020 | Passed | 0.226 s |
| 0020 → 0019 | Passed | 0.305 s |
| 0019 → 0018 | Passed | 0.199 s |
| 0018 → 0017 | Passed | 0.242 s |
| 0017 → 0022 again | Passed; 100,000 contacts, all unknown | 40.382 s |

Every pre-existing table retained its row count and original constraint definitions. Existing column type/default/nullability was checked; only the intended `messages.lead_id` relaxation was allowed at head, and it returned to NOT NULL at 0017. Head constraints/indexes were inspected, invalid wa_id/consent/cap updates were rejected, and account salts were non-null. The throwaway rehearsal database was dropped afterward.

The historical 0001 migration imports current model metadata. The synthetic runner therefore removes future outreach tables/columns after reaching 0017, and restores pre-0020 message nullability before seeding. This is explicitly synthetic reconstruction, not proof that an untouched production schema matches it.

The finished script was rehearsed twice. The table gives the latest run; the earlier run took 50.708 seconds for its first head upgrade and 2.021 seconds for its repeat. These are measured totals, not a guarantee or an attribution to one statement. No workload/lock contention benchmark was performed. Review the lock-sensitive statement table and safer alternatives in [the pre-deploy checklist](whatsapp-outreach-predeploy.md).

## The exact 23 baseline failures

```text
tests/test_campaign_routes.py::test_simulate_returns_rendered_message
tests/test_campaign_routes.py::test_simulate_no_match
tests/test_campaigns.py::test_create_campaign_with_keywords
tests/test_campaigns.py::test_any_media_and_specific_media_matching
tests/test_instagram_routes.py::test_disconnect_instagram_account
tests/test_instagram_routes.py::test_disconnect_instagram_account_is_idempotent
tests/test_instagram_routes.py::test_disconnect_pauses_active_campaigns_and_overview_count
tests/test_instagram_routes.py::test_reconnect_restores_account_and_token_without_reactivating_campaigns
tests/test_message_retry.py::test_retry_endpoint_accepts_failed_message
tests/test_message_retry.py::test_retry_endpoint_rejects_sent_message
tests/test_message_retry.py::test_retry_endpoint_rejects_expired_message
tests/test_meta_integration.py::test_mock_meta_connect_creates_account_and_encrypted_token
tests/test_meta_integration.py::test_token_is_not_plaintext_in_db
tests/test_send_private_reply.py::test_send_private_reply_success
tests/test_send_private_reply.py::test_send_private_reply_expired_private_reply
tests/test_send_private_reply.py::test_send_private_reply_token_error_no_retry
tests/test_send_private_reply.py::test_send_private_reply_retryable_500
tests/test_webhook_processing.py::test_duplicate_webhook_does_not_duplicate_message
tests/test_webhook_processing.py::test_comment_creates_comment_row
tests/test_webhook_processing.py::test_matching_active_campaign_creates_queued_message
tests/test_webhook_processing.py::test_duplicate_comment_does_not_duplicate_message
tests/test_webhook_processing.py::test_lead_is_created_from_comment
tests/test_webhook_processing.py::test_cooldown_prevents_message_queue
```

## Unresolved risks / work requiring external evidence

- Production snapshot has not been supplied. Snapshot restore mode, production row distributions, production PostgreSQL version and live lock/WAL/disk behavior remain unverified. The synthetic downgrade chain contains no newly sent leadless outreach messages; 0020's documented rollback guard still blocks those.
- 0022's volatile UUID default rewrites the account table. The safer nullable-column/backfill sequence is proposed, not implemented. 0018 holds shared-table ALTER locks through its backfill in the same upgrade transaction; deploy in a measured maintenance window or separately revise/rehearse the migration structure.
- The enable flag is global, not an account allowlist. Enabling just one account requires pausing all others operationally first. The first-day sequence documents this limitation.
- `WHATSAPP_BROKER_VISIBILITY_TIMEOUT_SECONDS` bounds task countdowns but does not configure Celery's Redis transport. The default 3600 values agree; changing only the env value would be unsafe. Confirm effective transport settings before deployment.
- Eager delivery does not prove real broker redelivery timing, worker death/restart behavior or dashboard browser flows. Real Meta onboarding, permissions, App Review, external recipients and actual delivery/read callbacks were not exercised. Meta documentation fetches returned 429; operator confirmation of current requirements remains necessary.
- Token canary coverage and AST checks prove the tested paths/known token echoes. They do not certify arbitrary future log code, reverse-proxy access logs or arbitrary secrets pasted into user-supplied evidence. Public signed URLs need proxy log redaction.
- Existing development test configuration emits short-HMAC-key and dependency deprecation warnings. Production secret values were not inspected; check production secrets without printing them.

## Reproduce the full test procedure

Run from the project root with the local disposable Docker services (never target persistent data). The inner Python passes configured credentials directly into child env variables without printing them.

```powershell
docker exec manyosirischat-postgres-1 createdb -U postgres whatsapp_phase7_tests
docker exec manyosirischat-redis-1 redis-cli FLUSHALL
docker exec -e APP_ENV=test -e RATE_LIMIT_ENABLED=false manyosirischat-backend-1 python -c "import os,subprocess; from app.core.config import settings; from sqlalchemy.engine import make_url; u=make_url(settings.DATABASE_URL).set(database='whatsapp_phase7_tests').render_as_string(hide_password=False); os.environ.update(DATABASE_URL=u,TEST_DATABASE_URL=u); raise SystemExit(subprocess.call(['python','-m','pytest','-q','--tb=no','--junitxml=/tmp/whatsapp-phase7-after.xml']))"
docker exec manyosirischat-postgres-1 dropdb -U postgres --if-exists whatsapp_phase7_tests
```

Pytest exits 1 because of the 23 baseline failures. Compare names, not only the count. `createdb` can be omitted only if that exact disposable DB already exists and is known to be empty.
