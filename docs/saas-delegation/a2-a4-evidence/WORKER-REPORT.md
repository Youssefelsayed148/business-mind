# Group 1: A2, A3, A4 ? 2026-10-28

Worktree: `D:/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/.closeout-worktrees/a2-a4`.
Branch: `closeout/a2-a4`, base `13c7873`. Changes are uncommitted as instructed. No main-checkout edits, push, merge, deployment, paid/provider call or shared-database access.

## Files changed

- `backend/alembic/versions/0019_whatsapp_outreach_settings.py`: inspect and verify existing type, nullability, default and named check expression before adding missing objects. Existing correct schema is unchanged. Incompatible schema fails with a named error. SQL literal values remain case-sensitive during deparser normalization. Revision IDs/ancestry/downgrade remain intact.
- `backend/app/api/routes_instagram.py`: hard-delete only (plus necessary imports). Require workspace owner permission and scope account lookup by workspace; delete outbound-idempotency references before messages and conversations before leads; delete per-channel forwarding rows; scrub the target account's Instagram entries from raw Meta webhooks, preserving other accounts' entries and dedupe markers. Other Instagram routes/dispatch/send handlers unchanged.
- `backend/tests/conftest.py`: join the fixture connection with a savepoint so production duplicate-handling rollback cannot roll back the fixture's outer transaction.
- Existing tests: `test_campaign_routes.py`, `test_campaigns.py`, `test_instagram_routes.py`, `test_instagram_token_refresh.py`, `test_message_retry.py`, `test_meta_integration.py`, `test_send_private_reply.py`, `test_webhook_processing.py`, `test_whatsapp_outreach_settings_migration.py`.
- New tests: `backend/tests/test_closeout_migrations.py`, `backend/tests/test_instagram_hard_delete.py`.
- This evidence directory only; shared PROGRESS/plan owned by lead.

## Tests added and repaired

Seven new migration cases: empty?head; a schema at actual 0022?head; downgrade to 0018 and upgrade?head; correct existing 0019 shape remains equal; wrong column type/default/nullability and wrong named constraint are refused; wrong-case SQL string literal (`'ARRAY'`) is refused. (The empty/head/0022/0018 rehearsal is one test; four original drift variants plus the review regression yield seven cases overall.) All schema transitions use Alembic; no stamp or create_all shortcut was introduced. The historical 0001 migration still uses its existing metadata bootstrap.

Three new hard-delete cases: conversations/messages/tokens/delegation rows removed and unrelated workspace/account rows preserved; mixed-account raw webhook entries preserved including malformed unrelated entries; repeat returns 404; admin lacks delete permission; workspace A/B resources hidden (404) and unauthorized workspace membership refused (403).

Fixture repairs retain substantive assertions. Workers use the fixture session and close is stubbed in these two test modules; processing runs synchronously while real Meta sends remain queued. Sync Meta client mocks replace AsyncMocks. The retry test asserts a retry is raised and its countdown. FK parents are flushed/seeded. Only mutation-role fixtures are promoted; read-only viewer coverage remains. Reconnect checks OAuth initiation then a mocked callback, the new active token and the historical expired token, paused campaign and the actual audit log. The development-only mock route is asserted absent under APP_ENV=test; token encryption round-trip is tested directly.

## Exact test commands and outcomes

Default-sandbox attempt of command 1 was denied by WSL `E_ACCESSDENIED` before any tests. The same command was approved through sandbox escalation. All four executions below used escalation, cwd this worktree, and the runner in this directory. The actual nested test command is `APP_ENV=test TEST_DATABASE_URL="$TEST_DATABASE_URL" pytest "$@" -q --junitxml="$evidence/tests.xml"`, as preserved in `test-inner.sh`.

1. `wsl -d Ubuntu -u root -- bash '/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/.closeout-worktrees/a2-a4/docs/saas-delegation/a2-a4-evidence/run-tests.sh' tests/test_campaign_routes.py tests/test_campaigns.py tests/test_instagram_routes.py tests/test_instagram_token_refresh.py tests/test_message_retry.py tests/test_meta_integration.py tests/test_send_private_reply.py tests/test_webhook_processing.py tests/test_whatsapp_outreach_settings_migration.py tests/test_closeout_migrations.py tests/test_instagram_hard_delete.py`

   Exit 1: **59 passed, 6 failed**, 14 warnings, 18.14s (`attempt-1.log/xml`). Failures: reconnect assumed the historical token row becomes active; four private-reply tests used async mocks against sync methods; duplicate request rollback erased worker changes committed inside the request session's open savepoint. Migration and hard-delete cases all passed.

2. `wsl -d Ubuntu -u root -- bash '/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/.closeout-worktrees/a2-a4/docs/saas-delegation/a2-a4-evidence/run-tests.sh' tests/test_instagram_routes.py::test_reconnect_restores_account_and_token_without_reactivating_campaigns tests/test_send_private_reply.py tests/test_webhook_processing.py`

   Exit 1: **11 passed, 2 failed**, 3 warnings, 1.77s (`attempt-2.log/xml`). Reconnect still queried the obsolete automation log rather than audit log; directly invoked Celery task retry raised its original exception because there is no worker request context. Corrected the log assertion and explicitly mock/assert retry scheduling.

3. `wsl -d Ubuntu -u root -- bash '/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/.closeout-worktrees/a2-a4/docs/saas-delegation/a2-a4-evidence/run-tests.sh' tests/test_instagram_routes.py::test_reconnect_restores_account_and_token_without_reactivating_campaigns tests/test_send_private_reply.py::test_send_private_reply_retryable_500`

   Exit 0: **2 passed**, 3 warnings, 1.25s (`attempt-3.log/xml`).

4. Reviewer found expression normalization incorrectly folded SQL string literals. Fixed normalization, added wrong-case literal test; also verified final hard-delete malformed-entry handling and import/doc cleanup:

   `wsl -d Ubuntu -u root -- bash '/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/.closeout-worktrees/a2-a4/docs/saas-delegation/a2-a4-evidence/run-tests.sh' 'tests/test_closeout_migrations.py::test_0019_refuses_incompatible_existing_shape[wrong-case-json-type]' tests/test_instagram_hard_delete.py`

   Exit 0: **4 passed**, 2 warnings, 2.80s (`tests.log/xml`).

`summary.json` independently aggregates JUnit: **66 unique targeted cases, all passing in their latest recorded execution**. This is iterative targeted evidence, NOT one green full-suite run. No full suite was run. Final integrated full-suite results remain **UNVERIFIED** and belong to the lead's one end-of-work run.

`python docs/saas-delegation/a2-a4-evidence/prepare_snapshot.py`: exit 0, source-only ZIP produced (removed after use). AST parse of every changed Python file: passed. `git -c core.safecrlf=false diff --check`: exit 0. Standalone lint/type tools: **UNVERIFIED**, not run.

## Isolation

Dedicated PostgreSQL cluster `/var/tmp/many-a2-a4-20261028/pg`, Unix socket `/var/tmp/many-a2-a4-20261028/socket`, port 55443, no TCP listener. Main disposable DB `many_test_a2_a4`; migration fixtures create and drop only fresh databases in that cluster. APP_ENV=test and TEST_DATABASE_URL explicitly set; DATABASE_URL deliberately equals that same disposable target because legacy migration fixtures require it. Runner prints host/db identity before testing; preflight verifies actual current_database and conftest's exact selected URL. Private Redis per network namespace; only loopback exists during tests; no external service can be called. No env files in source snapshot. Cached T0 Python 3.11 venv reused without dependency downloads. Every run stopped its PostgreSQL and Redis on exit; lead/other workers' clusters untouched.

## Open questions and risks

- D5 remains OPEN and was not changed. A16/end-customer cross-app erasure remains outside this group.
- Hard-delete now requires `X-Workspace-Id` and owner membership. The shared dashboard request client supplies workspace headers; direct API consumers must supply one. Account removal does not erase the SaaS remote copy and does not implement deauthorization/deletion callbacks.
- Existing audit/automation log retention and provider-wide webhook health are unchanged. Concurrent deletion versus an in-flight worker is not newly proven here.
- Other Instagram routes deliberately remain globally authorized in existing code; this group scopes only destructive hard-delete. Further Instagram tenant scoping is outside assigned ownership.
- Historical 0001 model-based schema bootstrap remains. Migration compatibility rejection prevents silently accepting drift; operator repair needs a separate reviewed migration.
