# R1 implementation and local evidence - 2026-10-28

Owner approval: schema, migration 0030 (parent 0029), two-phase erasure and
unresolved identity policy were explicitly approved in the implementation request.

## Implemented

- Provider-response-only `MetaGrantIdentity`: retained Facebook debug proof,
  verified app/user/Page grant; WhatsApp token/WABA/phone verification; distinct
  Instagram exchange/profile context. WhatsApp/Instagram callback namespaces
  remain unresolved. The operator ledger lists unresolved grants without subjects.
- Account/token/current grant commit atomically for all three OAuth flows;
  reconnect replaces old token material and mapping. Workspace-bound Instagram
  OAuth state replaces the default-workspace fallback. Dashboard supplies the
  workspace header for these OAuth mutations. Pending erasure blocks OAuth.
- Migration 0030 adds encrypted subject/context and namespace lookup plus the
  content-free durable job ledger. Legacy namespaces stay unresolved. Downgrade
  fails closed until jobs are locally erased AND remotely verified. Empty-install
  migration 0001 preserves the pre-0030 authorization shape for 0028 validation;
  no already-applied production schema is changed by that bootstrap repair.
- Owner-only Facebook/WhatsApp hard-delete routes return 202 + opaque job ID;
  replays reuse the scoped job. Phase 1 removes Meta tokens, disables processing,
  queues/reuses A16 and removes local customer data atomically. The regular forward
  sweep advances phase 2 after all exact HTTP 202 acceptances, or operator cleanup
  verification. Accounts/signing config remain until that boundary; authorization
  is removed in the final account transaction. Public callback receipts are never
  completed by acceptance. Failed/pending A16 survives retention and delegation off.
- Scoped child order covers conversations, messages/outbound links/ordinary forwards,
  FB keywords/cooldowns/comments, WA recipients/consent/contacts/templates/campaigns,
  automation logs, proven audit entities and only target entries in mixed webhooks.
  Unscoped audit text, missing signing config, legacy acceptance ambiguity and unknown
  remote identities go to operator action. No shared application User is deleted.

Instagram dispatch/send handlers and commit 59d3442 are unchanged. Its legacy
immediate hard-delete route is unchanged; use coordinated customer/A16 erasure
before removing a delegated Instagram account. Callback data deletion still needs
operator completion; unresolved grants never acquire an inferred callback mapping.

## Commands and actual outcomes

All DB runs used an allowlisted source snapshot at `.r1-validation/source`, with
no actual env/token/credential files. Each invocation of the harness created its
own PostgreSQL 18 cluster under `/var/tmp/many-r1-*`, `many_test_r1` database,
private Redis on port 56389 DB 1, and a loopback-only `unshare --net` namespace.
Only that run's services were stopped by its trap. Dummy secrets and mocked HTTP
were used; no Meta/OpenAI/SaaS/paid call. The snapshot included pre-existing,
uncommitted Batch T/A5 config/model corrections listed by the initial git status;
these are preserved, not silently included in this R1 commit. Clean committed-head
integration with those earlier corrections remains a separate release check.

Harness invocation (PowerShell, from batch-b):

```text
wsl -d Ubuntu -u root -- unshare --net bash '/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/.closeout-worktrees/batch-b/.r1-validation/run.sh'
```

The harness sets `APP_ENV=test`, explicit `TEST_DATABASE_URL` AND `DATABASE_URL`
to its fresh private socket, asserts `current_database() = many_test_r1`, prints
only host/database, runs `alembic upgrade head`, `alembic check`, then:

```sh
APP_ENV=test TEST_DATABASE_URL="$TEST_DATABASE_URL" pytest <selected files below> -q --junitxml="$scratch/evidence/targeted.xml"
```

Each evidence directory retains logs and JUnit; the retained harness constructs
the explicit synthetic environment without printing generated keys.
The changed subset is deliberately rerun after each relevant correction; no full
suite was run and no sum below is a single full-suite pass.

| Evidence under /var/tmp | Exact selected files relative to backend/tests | Outcome |
| --- | --- | --- |
| many-r1-Oy2MUsFR/evidence | None; migration gate | Failed at 0028 before tests because 0001 used current metadata; bootstrap repaired |
| many-r1-yys3vU8C/evidence | test_account_erasure.py test_meta_compliance.py test_contact_erasure.py test_saas_forwarder.py | 107 passed, 1 failed (A16 failed-payload purge); corrected |
| many-r1-GSxQW5zc/evidence | previous four + test_account_erasure_migration.py test_r1_oauth.py test_facebook_token_verification.py test_meta_integration.py | 135 passed, 3 fixture failures (template category and webhook marker); corrected |
| many-r1-FrffGGWN/evidence | previous eight + test_workspace_scoping.py test_instagram_routes.py | 149 passed, 1 stale token-row assertion failed; corrected |
| many-r1-tM5KFY6I/evidence | test_r1_oauth.py test_instagram_routes.py::test_reconnect_restores_account_and_token_without_reactivating_campaigns test_r19_csv_import.py | 16 passed, 1 fixture NameError; corrected (includes separate R19 CSV test) |
| many-r1-kmxFw8Fy/evidence | test_instagram_routes.py::test_reconnect_restores_account_and_token_without_reactivating_campaigns test_saas_delegation_config.py test_saas_retention.py | 62 passed, zero failures/errors/skips, 7.13 s |
| many-r1-aYmaFsZs/evidence | test_account_erasure.py test_r1_oauth.py | 38 passed, zero failures/errors/skips, 4.75 s, after final typed-proof/deletion-order changes |

Two earlier harness retries failed before services/tests: WSL initially required
sandbox escalation; a CRLF rewrite made `set -euo pipefail` invalid. Both were
corrected. No test success is claimed for them. One read-only inline WSL log
inspection had a shell-quoting error; it did not change source or services.

`test_account_erasure_migration.py` passed both cases in the 149-pass run:
empty -> 0029 -> head, 0022 -> 0029 -> head, legacy rows remain unresolved,
0030 downgrade/reupgrade, pending-job downgrade rejection with data retained,
verified-job downgrade/reupgrade and clean head `alembic check`. Every later
harness also passed fresh empty-to-head and clean `alembic check`.

Offline dashboard snapshot command:

```text
wsl -d Ubuntu -u root -- unshare --net bash '/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/.closeout-worktrees/batch-b/.r1-validation/tsc.sh'
```

`node node_modules/typescript/bin/tsc --noEmit --incremental false` exited 0;
`NEXT_TELEMETRY_DISABLED=1 node node_modules/next/dist/bin/next lint --file lib/api.ts`
exited 0, no warnings/errors. Cached dependencies only. `git diff --check --
backend dashboard/lib/api.ts` exited 0.

## Limits and release requirements

Historical 0001 still bootstraps current metadata for non-R1 tables; the 0022
checkpoint rehearsal is not a restored production historical-schema rehearsal.
Full suites, final clean-head integration, hosted CI, migration on a deployed
instance, Meta permission/namespace verification, live A16 completion and staging
are UNVERIFIED. In-flight worker memory still needs documented quiescence; this
does not recall sends. Legacy unknown remote scope and unscoped audit content
need operator investigation, never guessed scope or automatic completion.
Many/SaaS signing configuration must remain available until acceptance. Completed
minimal jobs expire only 30 days after independent SaaS verification; unresolved
failures are retained. Public-policy contact/effective-date inputs and publication
are owner gates. No push, merge or deploy was performed.

## Explicit R1 commit file list

- `backend/alembic/versions/0001_initial.py`
- `backend/alembic/versions/0030_meta_account_erasure.py`
- `backend/app/api/routes_facebook.py`
- `backend/app/api/routes_instagram.py`
- `backend/app/api/routes_meta.py`
- `backend/app/api/routes_whatsapp.py`
- `backend/app/integrations/meta/accounts.py`
- `backend/app/integrations/meta/facebook_oauth.py`
- `backend/app/integrations/meta/whatsapp_oauth.py`
- `backend/app/models/account_erasure_job.py`
- `backend/app/models/meta_authorization.py`
- `backend/app/services/account_erasure.py`
- `backend/app/services/meta_grant_identity.py`
- `backend/app/services/scoped_account_deletion.py`
- `backend/app/services/facebook_token_service.py`
- `backend/app/services/whatsapp_token_service.py`
- `backend/app/services/token_service.py`
- `backend/app/services/meta_compliance.py`
- `backend/app/services/saas_delegation_service.py`
- `backend/app/services/saas_forwarder.py`
- `backend/app/workers/saas_forward_tasks.py`
- `backend/tests/test_account_erasure.py`
- `backend/tests/test_account_erasure_migration.py`
- `backend/tests/test_r1_oauth.py`
- `backend/tests/test_facebook_token_verification.py`
- `backend/tests/test_instagram_routes.py`
- `backend/tests/test_saas_delegation_config.py`
- `backend/tests/test_workspace_scoping.py`
- `dashboard/lib/api.ts`
- `docs/data-deletion-runbook.md`
- `docs/saas-delegation/R1-DESIGN.md`
- `docs/saas-delegation/R1-IMPLEMENTATION.md`
- `backend/app/models/__init__.py`
- `docs/saas-delegation/PROGRESS.md`
- `docs/saas-delegation/CLOSEOUT-PLAN.md`


## Final identity/account binding review

The follow-up guard in `meta_grant_identity.save_grant` also requires the account
model's platform and its provider account identifier to equal the verified grant.
Being present in a provider grant list alone cannot attach proof to a different
account. The existing focused test now asserts wrong Page and wrong platform
rejection without a mapping write, then verifies successful replacement.

Same private harness command as above; selected tests:
`tests/test_account_erasure.py::test_provider_context_and_grant_failures tests/test_r1_oauth.py`.
Evidence `/var/tmp/many-r1-eXcWfH1t/evidence`: 16 passed, zero failures/errors/skips,
2.33 s, exit 0; fresh upgrade and Alembic check also pass. This targeted follow-up
is separate from the prior 38-case run, not a new full-suite claim. Explicit
follow-up files: the service, test_account_erasure.py, this report and the ticket
PROGRESS entry. No generated artifacts or unrelated source is staged.


## Callback matrix and phase-two transaction coverage

Completed the explicit unresolved/business-system-user/wrong-app replay matrix
for Facebook, WhatsApp and Instagram (nine cases), asserting one visible operator
receipt and no disconnection for unproven mappings. Added a phase-two rollback
case that restores account, authorization, job state and accepted event ledger
when the caller fails before commit. Same private harness command; selected:
`tests/test_account_erasure.py::test_callback_never_matches_unproven_namespaces tests/test_account_erasure.py::test_phase_two_rollback_preserves_account_grant_and_acceptance_ledger`.
Evidence `/var/tmp/many-r1-pwM6hMIH/evidence`: 10 passed, zero failures/errors/skips,
2.77 s, exit 0, with fresh upgrade/drift pass. No application code changed in
this coverage follow-up. Explicit files: test_account_erasure.py, this report
and the ticket-only PROGRESS entry.
