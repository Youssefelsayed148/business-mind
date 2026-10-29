# Many full-test evidence — 2026-10-29

Required local checks are green. D5 remains **OPEN** under the current owner
instruction; commit `59d3442` remains an ancestor and this session changed no
Instagram dispatch/send code. No release or live-service approval is inferred.

Tested branch: `closeout/batch-b`. Initial Windows Git HEAD:
`f8e9aa70b3fbb0a2af7bd8cff0db3f73f1338f84`, clean status. The tested source also
contains the reviewed `backend/tests/conftest.py` diff in `reviewed-fixture.diff`.
`source-manifest.json` records the fresh 383-file snapshot and SHA256 per file.
`counts.json` verifies those exact bytes match the final worktree. Earlier
snapshots differ only in that fixture; dashboard, scripts, migrations and
application source are identical across attempts.

| Final check | Passed | Failed | Errors | Skipped | Exit | Command wall seconds |
|---|---:|---:|---:|---:|---:|---:|
| Full backend | 1007 | 0 | 0 | 0 | 0 | 154.315 |
| Scripts unittest | 29 | 0 | 0 | 0 | 0 | 1.121 |
| Contract copies (3 hashes) | 1 check | 0 | 0 | 0 | 0 | 0.027 |
| Locked cached dependencies (`npm ls --all --json`) | 1 check | 0 | 0 | 0 | 0 | 0.655 |
| Dashboard TypeScript | 1 check | 0 | 0 | 0 | 0 | 2.684 |
| Dashboard full configured lint | 1 check | 0 | 0 | 0 | 0 | 2.311 |
| Final fixture regression session 1 | 3 | 0 | 0 | 0 | 0 | 1.539 |
| Final fixture regression session 2 | 3 | 0 | 0 | 0 | 0 | 1.413 |

Pytest reports 153.02 seconds and 58 warnings for the full backend; unittest
reports 0.991 seconds. Lint has one existing warning at dashboard accounts
page.tsx:510 (missing `toast` dependency). No warnings were disabled. The
dashboard dependency cache's package-lock JSON exactly matches the fresh source
lock; `npm ls` exited 0. No dependencies were fetched over the network.

Named subsets of the **same** 1007 backend passes (zero failures/errors/skips):

| Test file | Passes |
|---|---:|
| test_account_erasure.py | 31 |
| test_r1_oauth.py | 15 |
| test_account_erasure_migration.py | 2 |
| test_meta_compliance.py (callbacks included) | 32 |
| test_contact_erasure.py (A16 producer) | 26 |
| test_processed_event_service.py | 8 |
| test_processed_event_migration.py | 1 |
| test_saas_unsupported_instagram.py | 13 |
| test_meta_graph_version.py | 32 |
| test_r19_csv_import.py | 15 (14 export/security, 1 import) |

`counts.json` contains results for every backend test file. These subset counts
and repeated fixture regression passes must not be added to the full-suite total.
Scripts JUnit is a faithful conversion of the original verbose unittest log;
the conversion did not rerun tests. Original pytest JUnit is retained unchanged.

## Migration evidence

`attempt-2/commands.json` and its twelve migration logs record successful real
Alembic executions against two fresh databases:

1. `many_test_migrate_empty`: upgrade head, current, downgrade
   `0029_hash_processed_event_keys`, upgrade head, check.
2. `many_test_migrate_0022`: upgrade `0022_whatsapp_opt_in`, upgrade head,
   current, downgrade `0029_hash_processed_event_keys`, upgrade head, check.
3. `alembic heads`: exactly `0030_meta_account_erasure (head)`.

All twelve exit 0. Both drift checks report no new upgrade operations. Exact
durations are recorded individually, not estimated. No stamping or direct
metadata schema shortcut was used by the harness or final fixture. The existing
historical `0001_initial` Alembic migration internally bootstraps metadata;
this session did not rewrite historical migration implementation.

## Failed and interrupted attempts

All attempts use fresh snapshots and new private clusters; none is hidden or
reported as a pass.

* Initial WSL invocation was denied before execution; approved sandbox escalation
  enabled WSL. A subsequent pre-service harness launch exited 1 because the
  Windows worktree `.git` pointer is not directly usable by Linux Git. The harness
  now passes explicit git-dir/work-tree paths. No suite ran in those launches.
* **attempt-1:** full backend exit 1, **0 passed / 0 failed / 1007 setup errors /
  0 skipped**, 30.06 pytest seconds / 31.283 wall seconds. Harness/fixture used
  `python -m alembic`; the repository's local migration package has no `__main__`.
  The twelve migration commands failed for that same invocation error (each
  exact exit/duration retained). Scripts, contracts, dependency check, TypeScript
  and full lint passed here and were not repeated. Corrected invocation uses the
  cached virtualenv's Alembic console entrypoint. Linux Git's CRLF status differs
  from Windows Git and is not authoritative; the initial manifest's Linux status
  is retained for transparency. Its source hashes remain valid; no forbidden
  file was copied into any source snapshot.
* **attempt-2:** model regression **3 passed**, exit 0, 1.03 pytest / 1.644 wall
  seconds. The next full run found the original metadata-drop teardown had removed
  tables while leaving `alembic_version` at head. Interrupted after 93.608 wall
  seconds, exit **-15** (SIGINT did not promptly return; SIGTERM targeted only
  this run's pytest PID 3326). Progress output records **252 pass markers,
  169 failure markers and 93 error markers**, 514 completed markers; it is
  **not** a completed-suite count. No final JUnit was produced. No skip was
  introduced. The required migration rehearsals then passed independently.
* **attempt-3:** rejected teardown design attempted `alembic downgrade base`.
  Test bodies: **3 passed**, plus **1 teardown error**, exit 1, 1.76 pytest /
  2.292 wall seconds. JUnit marks one of the three cases as an error, hence
  two pass-only cases and one error case. The private cluster's error diagnostic
  identifies missing index `ix_conversations_instagram_account_id` on the legacy
  base rollback path. Other duplicate-key diagnostics were expected assertions
  in the model tests. Base rollback is outside the requested 0030↔0029 scope
  and remains a documented limitation; no claim of successful base rollback.
* **Final:** fixture runs real Alembic upgrades, disposes connections, and leaves
  private database destruction to its owning harness. Two consecutive fixture
  regression sessions passed before the full suite's **1007 passes**.

The only committed code fix is the fixture lifecycle. No application code,
authorization, tenant boundaries, erasure logic, dedupe logic, or meaningful test
assertions changed. No skips or xfails were added. PostgreSQL and Redis instances
started by each run were stopped in `finally`; `teardown.json` records each.

## Commands, isolation and artifacts

`commands.json` in each attempt contains exact expanded test/check commands,
working directories, exit codes and measured wall durations. All test commands
explicitly set `APP_ENV=test`, `TEST_DATABASE_URL` and `DATABASE_URL`. Before
each, `run.py` prints only the database host/name and asserts `current_database()`
through psql. `conftest.py` reads the explicit target ahead of fallback settings.
Migration fixture subprocesses also receive the explicit disposable URL.

WSL launcher (PowerShell also set APP_ENV=test and an inert preflight
TEST_DATABASE_URL; no application/database commands ran on that preflight URL):

```text
wsl -d Ubuntu -u root -- env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin APP_ENV=test TEST_DATABASE_URL=postgresql://dummy@/many_preflight unshare --net /var/tmp/many-t0-20261028/venv/bin/python '/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/.closeout-worktrees/batch-b/docs/saas-delegation/many-full-test-evidence/run.py'
```

The final launcher adds `backend-only`; earlier passing checks are not repeated.
Harness versions used in attempts are represented by their command records and
reviewed fixture diffs; the current run.py contains the corrected entrypoint,
two-session regression and host/name-only command summary output. Earlier
console summaries included dummy connection URLs; they contained no passwords.

Each run initializes PostgreSQL 18 under `/var/tmp/many-r1-full-*`, Unix socket,
empty listen_addresses; a new Redis binds 127.0.0.1:56390 in the same loopback-only
network namespace. `env -i` prevents inherited provider credentials. Only dummy
secrets are configured. The source allowlist excludes actual env files, token
files, credential files, dumps, backups, caches, old validation snapshots and
generated dashboard output. No source ZIPs, dependencies, database files or
browser state are included in these evidence artifacts. The stopped clusters
and source snapshots remain only in private WSL scratch storage.

Source review after completion: all 383 final snapshot hashes match the worktree;
all earlier passing-check source files match too, except the deliberately changed
backend fixture. `reviewed-fixture.diff` is the exact tested worktree difference
relative to initial HEAD (Linux Git represents CRLF changes more verbosely).

PROGRESS and the local plan are updated; the existing SaaS plan copy is kept
byte-identical. No other SaaS files were edited by this run.

Final validation: authored code/document diffs pass `git diff --check`.
A whole-artifact staged whitespace check reports pytest's original trailing
spaces in failure tracebacks/JUnit and initdb's blank final line; those raw
artifacts are preserved verbatim rather than edited to satisfy a prose check.
`commit-files.txt` lists every file selected for the explicit local commit.

## Limits

Still **UNVERIFIED**: live Meta/v26 compatibility, staging/canary, unresolved
identity operator remediation, deployment/hosted CI, policy publication, D4
recordings, real SaaS round trip and receiver/runtime behavior. D5 stays OPEN.
The legacy downgrade-to-base missing-index limitation is not repaired by this
testing-fixture change. No push, merge, deployment, live send, authenticated
external call, paid API or cloud resource was used.
