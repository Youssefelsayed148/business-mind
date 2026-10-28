# Group 3 ? B1/B3/B4 ? 2026-10-28

Worktree `.closeout-worktrees/b1-b4`; branch `closeout/b1-b4`; base `bfb1cc8`.
No commit, push, merge, deployment, live send, paid or authenticated provider call.
No main-checkout edits. OAuth callbacks and Instagram dispatch/send code untouched.

## Outcome and limits

**B1/R1 PARTIAL.** Strict signed Meta callbacks, durable operator-action receipts,
opaque public status and an explicit operator remediation CLI are implemented.
There is no fabricated automatic callback-admin mapping. Existing OAuth does not
persist sufficiently grounded callback-subject ownership for all three platforms.
Facebook/WhatsApp full admin-account deletion is also not supplied by this patch.
Unmapped and unverified erasure requests remain pending; no completed-erasure claim
is based on callback receipt or queue acceptance. B3/B4 are draft policy/review text
for owner review, not published documents or a claim of Meta eligibility/approval.

For independently verified app/admin/workspace/channel mappings, valid callbacks
physically remove stored tokens, disconnect the correct account, turn AI/delegation
off and drop ordinary pending forwards while preserving A16 erasure rows. Workspace
scope is required on the account query; an invalid cross-workspace mapping cannot
affect the target. Historical completed callback replay cannot revoke a newly
verified grant. Mapping after an unresolved callback reconciles it immediately.

## Files changed

- New `backend/app/api/routes_meta_compliance.py`: bounded form callbacks at
  `/meta/compliance/{instagram|facebook}/deauthorize` and `/data-deletion`;
  public `/meta/data-deletion/status/{code}`.
- New `backend/app/services/meta_compliance.py`: strict canonical base64url,
  HMAC-SHA256 verification, duplicate JSON-key/type/algorithm/size validation,
  app-separated identity digests, idempotent receipts, targeted disconnection,
  audit records and CLI (`map`, `list-pending`, `complete`). CLI requires a dedicated
  database env name, defaults to rollback, accepts verified subject on stdin,
  validates workspace/channel selection and requires both-app completion attestations.
- New `backend/app/models/meta_authorization.py`, `data_deletion_request.py`.
  No raw admin ID, signed request or message body stored. Mapping ownership is
  operator-verified; workspace FK cascades only those mapping rows on deletion.
- New Alembic `backend/alembic/versions/0028_meta_compliance.py`, chained on 0027.
  Existing correctly shaped tables are validated for columns/types/nullability,
  PK/unique/FK constraints so the historical 0001 current-metadata bootstrap does
  not cause duplicate-table failure. No create_all/stamp workaround in migration.
- `backend/app/models/__init__.py`, `backend/app/main.py`: separate registrations.
- `dashboard/app/(auth)/privacy/page.tsx`, `terms/page.tsx`: processor/AI/window,
  real retention and operator-coordinated deletion wording within existing layout.
- `docs/meta-app-review-submission.md`, new `docs/data-deletion-runbook.md`: honest
  evidence checklist, native permission and delegated recordings, concrete scoped
  operator commands, blockers and no premature A16/live claims.
- New `backend/tests/test_meta_compliance.py`; evidence in this directory.

## Tests and exact command outcomes

All WSL test runs use the private new cluster
`/var/tmp/many-b1-b4-20261028/pg`, socket
`/var/tmp/many-b1-b4-20261028/socket`, port 55438, DB `many_test_b1_b4`, no TCP
listener. APP_ENV=test and TEST_DATABASE_URL explicitly set on every test command;
host/db identity printed and actual DB/conftest URL asserted. DATABASE_URL is an
unreachable required-setting sentinel. Cached T0 Python 3.11 dependencies; source
snapshot excludes environment files. Private Redis inside per-run loopback-only
`unshare --net` namespace, FLUSHALL only there. Every run stopped its own PostgreSQL
and Redis. No external interface exists during tests.

1. `git worktree add -b closeout/b1-b4 .closeout-worktrees/b1-b4 feature/saas-delegation`
   (from parent root, sandbox escalation): exit 0, base bfb1cc8.
2. `python -m compileall -q backend/app/services/meta_compliance.py backend/app/api/routes_meta_compliance.py backend/tests/test_meta_compliance.py backend/alembic/versions/0028_meta_compliance.py`:
   exit 0. `git diff --check`: exit 0 (CRLF conversion advisories only).
3. `wsl -d Ubuntu -u root -- bash '/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/.closeout-worktrees/b1-b4/docs/saas-delegation/b1-b4-evidence/run-tests.sh'`:
   exit 0. Nested `APP_ENV=test TEST_DATABASE_URL="$TEST_DATABASE_URL" pytest tests/test_meta_compliance.py -q --junitxml="$evidence/tests.xml"`:
   **28 passed**, 0 failed/errors/skips, 1 dependency warning, 0.93 s. Retained
   `tests-first.log/xml`. Standalone 0028 operations rehearsal also passed (initial
   `migration-first.log`), proving creation, repeat-upgrade validation, drift
   rejection and down/up; it does not prove full 0001?head or 0027?0028 via CLI.
4. Review found completed historical callback replay could affect a reconnected
   grant. Corrected that and added focused CLI regressions. Only related new tests
   rerun: `wsl -d Ubuntu -u root -- bash '/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/.closeout-worktrees/b1-b4/docs/saas-delegation/b1-b4-evidence/rerun-focused.sh'`:
   exit 0. Nested pytest `tests/test_meta_compliance.py -k 'completed_callback_replay or cli_' -q`:
   **3 passed, 28 deselected**, 1 dependency warning, 0.81 s. Current `tests.log/xml`.
   The final module has 31 collected cases, but no 31-case whole-module result is
   claimed after the review correction; the final integrated suite belongs to lead.
5. Workspace mapping FK was changed to CASCADE to avoid blocking existing workspace
   deletion. Only migration rehearsal rerun:
   `wsl -d Ubuntu -u root -- bash '/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/.closeout-worktrees/b1-b4/docs/saas-delegation/b1-b4-evidence/rerun-migration.sh'`:
   exit 0, same three PASS lines in final `migration.log`.
6. Related policy page type check using cached parent dashboard dependencies:
   `node ../../dashboard/node_modules/typescript/bin/tsc --noEmit --incremental false --jsx preserve --lib DOM,ES2020 --moduleResolution node --esModuleInterop --skipLibCheck --typeRoots ../../dashboard/node_modules/@types --baseUrl ../../dashboard/node_modules 'dashboard/app/(auth)/privacy/page.tsx' 'dashboard/app/(auth)/terms/page.tsx'`:
   exit 0, no output. No dependency install, full frontend build or broad lint run.
7. Independent XML parse verifies initial 28 and focused 3 cases have zero failures,
   errors or skips. Temporary source-only `source.zip` removed after tests; scripts,
   migration rehearsal, logs and XML retained. Final whitespace check required by
   lead before integration; no full suite run here.

Added coverage: malformed/bad-HMAC/invalid-type/algorithm/duplicate-key/oversize
callbacks; Unicode handling; app namespace isolation; no Page-ID equality inference;
three-platform mapped revocation; cross-workspace mismatch; pending/opaque status;
idempotency and completed replay; operator proof/attestation requirements;
post-receipt verified mapping; preserved erasure outbox; explicit CLI DB/dry-run.

## Public documentation and remaining work

Public-only web lookups were authorized. Exact attempted official URLs:

- https://developers.facebook.com/docs/development/create-an-app/app-dashboard/data-deletion-callback/ ? HTTP 429.
- https://developers.facebook.com/docs/facebook-login/guides/advanced/manual-flow/#deauth-callback ? HTTP 429.
- https://developers.facebook.com/docs/facebook-login/guides/access-tokens/debugging-and-error-handling/ ? tool-inaccessible.

No external result established identity namespaces, callback eligibility or live
behavior. Future OAuth mapping automation needs authoritative provider evidence
and new tests. Legacy operator reconciliation, full FB/WA admin erasure, actual
Meta callback/dashboard configuration, public URL runtime, receipt retention
policy and staging verification remain UNVERIFIED. APP_SECRET_KEY rotation changes
identity digests and requires planned re-verification/reconciliation; runbook warns.

D5 remains OPEN per owner direction. No account erasure is marked completed in
this work. Publishing policy text, production changes and live actions require
separate approval. Lead must adapt prior canary source tests that assumed 0027
is always head now that legitimate 0028 exists; retain required ancestry checks.


## Lead review correction: CLI initialization failure

Lead found `create_engine(raw_url)` ran before the CLI error-sanitizing try
block. Invalid configuration could therefore raise an unsanitized exception.
Moved initialization into the protected block, guarded disposal, and added
a regression that injects a synthetic credential marker into an initialization
exception and asserts only the generic failure is returned with no marker.

Exact command (sandbox escalation):
`wsl -d Ubuntu -u root -- bash '/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/.closeout-worktrees/b1-b4/docs/saas-delegation/b1-b4-evidence/lead-cli-check.sh'`
Nested: `APP_ENV=test TEST_DATABASE_URL="$TEST_DATABASE_URL" pytest tests/test_meta_compliance.py -k 'engine_initialization_errors' -q --junitxml="$evidence/lead-cli.xml"`.
Exit 0: **1 passed,31 deselected in 0.14s**. Same private cluster/socket/DB and
loopback-only namespace as above; PostgreSQL and Redis stopped. Source snapshot
ZIP removed. No full module/suite rerun; final module has 32 collected cases.


## Lead review correction: named upsert constraint and lookup indexes

Migration 0028 originally accepted a uniquely constrained column set with a
different constraint name, but runtime upserts require the exact named
`uq_meta_authorization_channel`. It also skipped missing lookup indexes for
an already existing table, making downgrade fail. Added exact-name validation
and safe creation/shape validation of the two expected lookup indexes.

The standalone migration rehearsal now also renames the unique constraint
and proves rejection, then removes a lookup index and proves safe repair.
Exact command (sandbox escalation):
`wsl -d Ubuntu -u root -- bash '/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/.closeout-worktrees/b1-b4/docs/saas-delegation/b1-b4-evidence/lead-migration-check.sh'`
Exit 0: all five PASS assertions, including the previous creation/no-op,
column drift and downgrade/upgrade checks. Retained `lead-migration.log`;
no full test suite. Same disposable DB and disabled external network;
PostgreSQL/Redis stopped. No schema from outside the private test cluster used.
