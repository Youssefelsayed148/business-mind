# Group 4 B2 ? 2026-10-28

Worktree: `D:/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/.closeout-worktrees/b2`.
Branch `closeout/b2`, base `51c0d62`. Changes uncommitted as instructed. No main-checkout edits, external/provider call, push, merge, deployment or paid service. No credential/env files read. The owner-approved dedupe privacy fix is implemented below; integration/full-suite and live remote completion remain unverified.

## Files changed

- New `backend/app/services/contact_erasure.py`: transactional local erasure, atomic A16 outbox, source-account/customer raw webhook scrubbing, explicit retry and30day raw payload purge. No commits, Celery execution, HTTP or AI call in the service.
- New `backend/app/api/routes_contact_erasure.py`: workspace owner/admin POST erase, GET status and POST retry routes under `/privacy/contact-erasure/{platform}/{channel_id}`. Identity is JSON-body-only; server-side channel workspace scope and role validation; input limits/controls; sanitized audit/count responses.
- `backend/app/main.py`: standalone import and router include only; B1's separate registration is disjoint.
- `backend/app/services/saas_forwarder.py`: A16 exemptions only. `drop_pending` excludes erasure, delivery accepts erasure with delegated chat disabled, missing channel/config and changed original connection become explicit failures without HTTP. Existing retry/budget/signing policies remain.
- `backend/app/workers/saas_retention_tasks.py`: existing daily task clears30day raw webhook bodies and reports counts. Beat schedule remains four entries; no new task/schedule.
- New `backend/tests/test_contact_erasure.py`, `backend/tests/test_webhook_retention.py`; appended only A16 helper/cases to `backend/tests/test_saas_forwarder.py`.
- New `docs/end-customer-erasure-runbook.md`; this evidence directory only. Shared PROGRESS/plan and policy/submission pages remain lead/B1 owned.

## Behavior and tests

Local cleanup covers scoped lead/conversation/message rows, outbound idempotency references, Instagram/Facebook comments/cooldowns, identifiable automation logs, WhatsApp contacts/recipient/consent records and lead-less outreach messages. Business account/campaign/template configuration remains. Ordinary queued forwards are dropped and all matching ordinary event payloads cleared. Mixed-account/customer raw webhook items are preserved; a body with only erased customer items becomes SQL NULL with pending work skipped.

A16 events contain exactly the envelope plus connection and external contact identity, no name/body/separate phone field/tenant/bot. Event ID is a deterministic opaque UUID from channel+request+input identity. Missing identity is idempotent; repeating the same request never recreates a second event after local deletion. Local erasure/outbox/audit commit once together; an injected failure after queue/deletes rolls everything back. Scope tests include tenantA/B, same identity on different platforms and another channel in the same workspace, forbidden roles/headers and Facebook ASID?PSID resolution.

Fake-SaaS forward tests verify signing, ordinary drop versus erasure survival on disablement, missing/changed signing target refusal, revoked401 retries and explicit24h failure. Retry works with delegated chat off and refuses silently changing the original connection. Status distinguishes queued, accepted_not_completed and operator_action_required; a202 is never claimed as remote completion. No new remote-completion protocol is invented.

Retention tests verify exact30day boundary, SQL NULL versus JSON null idempotence, dedupe/status row preservation, sanitized count logging and existing four-task schedule.

## Exact commands and outcomes

All from the B2 worktree. Source-only snapshot preparation: `python docs/saas-delegation/b2-evidence/prepare_snapshot.py` exited0 before each run. Cached T0 Python3.11 reused without downloads. The preserved `run-tests.sh`/`test-inner.sh` show cluster startup, loopback-only network namespace, per-run Redis, DB preflight and exact nested `APP_ENV=test TEST_DATABASE_URL="$TEST_DATABASE_URL" pytest "$@" -q --junitxml="$evidence/tests.xml"` command.

1. `wsl -d Ubuntu -u root -- bash '/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/.closeout-worktrees/b2/docs/saas-delegation/b2-evidence/run-tests.sh' tests/test_contact_erasure.py tests/test_webhook_retention.py tests/test_saas_forwarder.py tests/test_saas_retention.py`

   Exit1:68passed,1failed,3warnings,3.07s (`attempt-1.log/xml`). The atomicity test's rollback removed seeded fixtures because base51c0d62 lacked reviewed A3 savepoint conftest. No production commit exists inside the service. Lead approved overlaying A3's conftest into the disposable source snapshot only. Its exact copy/hash is retained as `a3-conftest.py` and `summary.json`; the worker checkout's conftest is unchanged. This is combined-source test evidence expected at integration.

2. `wsl -d Ubuntu -u root -- bash '/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/.closeout-worktrees/b2/docs/saas-delegation/b2-evidence/run-tests.sh' tests/test_contact_erasure.py::test_queue_failure_rolls_back_every_local_change tests/test_contact_erasure.py::test_same_identity_on_second_channel_in_same_workspace_is_preserved tests/test_contact_erasure.py::test_comments_cooldowns_and_identifiable_automation_logs_are_erased tests/test_contact_erasure.py::test_whatsapp_outreach_messages_recipients_and_consent_are_erased tests/test_contact_erasure.py::test_only_customer_webhook_body_is_sql_null_and_pending_work_is_skipped`

   Exit1:4passed,4failed,1warning,2.06s (`attempt-2.log/xml`). Atomicity passed with approved A3 fixture overlay. Three new same-workspace/channel test fixtures omitted a required synthetic connection_id; the new outreach fixture omitted campaign.created_by. All four failed before erasure. Repaired fixture fields without weakening assertions.

3. `wsl -d Ubuntu -u root -- bash '/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/.closeout-worktrees/b2/docs/saas-delegation/b2-evidence/run-tests.sh' tests/test_contact_erasure.py::test_same_identity_on_second_channel_in_same_workspace_is_preserved tests/test_contact_erasure.py::test_whatsapp_outreach_messages_recipients_and_consent_are_erased`

   Exit0:4passed,1warning,1.18s (`attempt-3.log/xml`).

4. Refined log matching to recognized identity/reference fields, preserving another customer's body even when it equals the erased identity. Then:

   `wsl -d Ubuntu -u root -- bash '/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/.closeout-worktrees/b2/docs/saas-delegation/b2-evidence/run-tests.sh' tests/test_contact_erasure.py::test_comments_cooldowns_and_identifiable_automation_logs_are_erased`

   Exit0:2passed,1warning,0.92s (`tests.log/xml`).

`summary.json` independently aggregates76unique cases, all passing at their latest execution. These are iterative targeted runs, not one green full suite. No full suite was run. AST parse of every changed Python file passed; `git -c core.safecrlf=false diff --check` passed. Lint/type check and final integrated full suites: UNVERIFIED, not run. Source ZIP removed after use.

## Isolation

Dedicated PostgreSQL cluster `/var/tmp/many-b2-20261028/pg`; socket `/var/tmp/many-b2-20261028/socket`, port55444, no TCP listener; database `many_test_b2`. APP_ENV=test and TEST_DATABASE_URL explicit on every pytest command; host/db identity printed and actual current_database/conftest selection asserted. DATABASE_URL same explicitly disposable target. Private Redis per network namespace; loopback only, no external network. No shared Redis/DB touched. PostgreSQL/Redis teardown succeeded after every run.

## Open questions and risks

- Superseded by the owner-approved hashing extension below: processed-event keys are opaque versioned digests, diagnostic metadata is erased, and database guards protect new writes. Existing external operational logs still follow their own retention; live handler code was not refactored.
- Forward worker advisory locks coordinate stored ordinary queues before erase. Existing inbound/send handlers do not participate in the erasure lock, and data already in a worker's memory or already delivered cannot be recalled. The runbook requires owner-approved quiescence/verification; no live action was performed.
- The local response cannot observe SaaS background-job completion. Accepted202 remains accepted_not_completed until separately verified. A missing/revoked original signing configuration requires manual remediation; it is never silently repointed or represented as remotely completed.
- Failed outbox payloads follow existing7day retention and terminal rows30days. After payload purge, explicit replay is unavailable; the secured privacy case/manual process remains required.
- No dashboard button added; the requested admin action is an authenticated API endpoint with a runbook. No Meta callback or business-admin mapping changes made in B2.
- Provider inboxes, backups, historical external logs and unstructured records lacking a provable customer relationship remain outside this local transaction. Do not make broader deletion claims than evidence supports.


## Owner-approved hashed-dedupe extension ? complete, 2026-10-28

The owner explicitly approved modifying the shared dedupe helper and adding its
migration. No Instagram dispatch/send handler changed. Additional owned files:

- `backend/app/services/processed_event_service.py`: hash at the storage boundary,
  preserving existing raw key builders and platform/provider namespaces. A
  per-key transaction advisory lock serializes claims; the unique constraint is
  retained. Existing raw/hash rows normalize to one oldest tombstone and return
  duplicate without reprocessing or rolling back unrelated caller changes.
  Metadata is discarded, event types are allowlisted and this helper logs only
  opaque event digests. Repeated normalization does not double-hash.
- `backend/app/models/processed_webhook_event.py`: matching guards require a
  versioned74-characterSHA-256 key, SQL-NULL metadata and an allowlisted event
  type (or NULL). This prevents an old writer from persisting raw keys or
  personal diagnostic data after rollout.
- `backend/alembic/versions/0029_hash_processed_event_keys.py`, down_revision
  `0028_meta_compliance`: exclusive table lock, bounded500-row pages, hash raw
  historical keys, merge raw/hash duplicates within each provider while keeping
  the oldest timestamp, erase metadata and unrecognized event types, add the
  matching database checks. No extension/dependency required.
- New `backend/tests/test_processed_event_service.py` and
  `backend/tests/test_processed_event_migration.py`; runbook rollout/rollback
  notes updated. No existing raw key-builder assertions needed changing because
  caller APIs remain unchanged.

Downgrade removes only the schema guards. It never reconstructs raw IDs/text or
metadata. It is not safe to resume old raw-key code after downgrade. Deployment
and rollback must pause old API/worker writers, and any recovery plan must retain
that pause until compatible code is ready. No live migration occurred.

### Exact focused commands and outcomes

5. `wsl -d Ubuntu -u root -- bash '/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/.closeout-worktrees/b2/docs/saas-delegation/b2-evidence/run-tests.sh' tests/test_processed_event_service.py tests/test_processed_event_migration.py tests/test_webhook_processed_logging.py`

   Exit0: **10passed in4.82s** (`attempt-5.log/xml`, identical archival
   `hash-tests.log/xml`). Seven shared-helper tests include true two-thread
   concurrent claims (exactly oneTrue), legacy/raw-plus-hash collision handling,
   provider/platform isolation, metadata/log privacy and preservation of caller
   changes. One real Alembic0028?0029 test covers historical data, collisions,
   refused raw writers and two downgrade/upgrade cycles without restoring raw
   data/double hashing. Two existing platform processed-log tests pass.

   Migration rehearsal uses a source snapshot ONLY with the approved A2
   migration0019 guard, A3 conftest and B1 migration0028 overlaid. These exact
   companion copies and SHA-256 hashes are retained as `a2-0019-overlay.py`,
   `a3-conftest.py`, `b1-0028-overlay.py` and `summary.json`. Companion files in
   the B2 checkout were not modified. The fixture upgrades via actual Alembic
   from empty to0028; it removes current-model-created new guards to emulate
   historical0028, seeds synthetic legacy rows, then upgrades to0029. No stamp
   or create_all shortcut introduced.

6. Reviewer requested portable disposable DB validation for the next full-suite
   session and a database guard for personal event_type values. Tests now require
   explicit APP_ENV=test and TEST_DATABASE_URL, a `many_test`/safe suffixed DB
   name and an absolute private `/var/tmp/` or `/tmp/` Unix socket (no TCP/DNS).
   Added the matching event-type database CHECK and its focused rejection test.

   `wsl -d Ubuntu -u root -- bash '/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/.closeout-worktrees/b2/docs/saas-delegation/b2-evidence/run-tests.sh' tests/test_processed_event_service.py::test_concurrent_duplicate_claims_process_at_most_once tests/test_processed_event_migration.py tests/test_processed_event_service.py::test_database_refuses_personal_event_type_even_with_an_opaque_key`

   Exit0: **3passed in5.46s** (`tests.log/xml`). No broader rerun.

Final aggregation: **87unique focused cases, all passing in their latest
recorded run**, with all failed attempts retained. This remains iterative
related-test evidence, not a full-suite pass. The owner's latest instruction
explicitly defers full testing to a new session. AST parsing and diff whitespace
checks pass; full suites, production migration, provider integration and live
remote erasure completion remain UNVERIFIED. No commit/push/merge/deploy by worker.
