# R19 Many verification - 2026-10-28

Worktree batch-b, branch closeout/batch-b. SaaS evidence and commit are recorded
in batch-c/implementation/R19-VERIFICATION.md and commit 86c992d.

## Changes and findings

Many has no _PHONE_SHAPE phone-export exemption. Its WhatsApp CSV import already
requires an explicit plus and exact normalized digits, so =, +formula, - and @
inputs are rejected. Added an import regression with four formula phones and a
valid international number, checking workspace A writes and no B writes.

A related real Many gap was found: /leads/export.csv wrote customer-controlled
names, identifiers, campaign/account labels as raw cells. The export now escapes
leading =, +, -, @, tab and carriage return on every data cell. Numeric identifiers
and ordinary text are unchanged. Tests cover each prefix and an actual CSV response,
including malicious account labels and -1-1. This is output formatting only; it
does not rewrite stored values or change the legacy export authorization/query.

The pre-existing uncommitted Batch T metadata corrections were reviewed and are
explicitly adopted in this R19 commit: register ProcessedWebhookEvent in the base
model registry and declare its already-migrated received_at index. Their existing
independent-process regression is included. No new migration is required. Other
pre-existing A5/config/template/canary/docs edits remain unstaged and preserved.

SaaS already has the requested phone guard, existing 0030 health expression index
and bot/provisioning model alignment. Its new migration regression plus existing
contacts/tenant A-B/health/prompt tests pass (41 cases). S10 does not exist in the
current rebuild prompt; the old historical PROGRESS mention does not justify an
invented requirement. No SaaS migration after 0031 was added; C3 head source check
still passes. Provider-global webhook_unhealthy was not changed in either repo.

## Exact related commands and outcomes

PowerShell from batch-b:

```text
wsl -d Ubuntu -u root -- unshare --net bash '/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/.closeout-worktrees/batch-b/.r1-validation/r19.sh'
```

Each run creates its own private PostgreSQL 18 cluster under /var/tmp/many-r19-*,
base DB many_test_r19, private Redis port 56390 DB 2, loopback-only namespace,
allowlisted env-free source snapshot and dummy secrets. APP_ENV=test,
TEST_DATABASE_URL and DATABASE_URL explicitly target that new socket; actual
current_database is asserted and only host/database is printed. No provider,
SaaS or paid call. Traps stop only services started by the run.

The harness runs alembic upgrade head and alembic check, both exit 0 with no
new upgrade operations, then:

```sh
APP_ENV=test TEST_DATABASE_URL="$TEST_DATABASE_URL" pytest <selected files> -q --junitxml="$scratch/evidence/targeted.xml"
```

| Evidence | Selected backend/tests files | Outcome |
| --- | --- | --- |
| /var/tmp/many-r19-37BfM5v9/evidence | test_r19_csv_import.py test_model_registry.py test_processed_event_migration.py | 3 passed, zero failures/errors/skips, 14.01 s |
| /var/tmp/many-r19-o4bKwjek/evidence | test_r19_csv_import.py (expanded with output guards) | 8 passed, zero failures/errors/skips, 3.73 s |

The migration test rehearsed actual dedupe upgrade/downgrade/reupgrade inside the
private cluster. The output-only change did not require rerunning unrelated
schema tests. A Python crypt deprecation warning remains. The runs above are
separate targeted checks, not a full-suite pass.

Both CI workflow definitions were parsed with yaml.BaseLoader and checked for
manual-only events, bash -n syntax, and existing script/test/npm command targets:

```text
wsl -d Ubuntu -u root -- /var/tmp/saas-closeout-tools/venv/bin/python '/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/.closeout-worktrees/batch-c/.r19-validation/ci_static.py'
```

Exit 0: 4 Many and 14 SaaS run blocks checked, not executed. Exact SaaS tests,
initial setup failure/correction, 0030 index round-trip and clean drift, Ruff
checks and the C3 one-test source result are in its R19-VERIFICATION.md.
`git diff --check` for all changed Many R19 source/test files passed.

## Explicit Many commit files and limits

- backend/app/api/routes_dashboard.py
- backend/app/models/__init__.py
- backend/app/models/processed_webhook_event.py
- backend/tests/test_model_registry.py
- backend/tests/test_r19_csv_import.py
- docs/saas-delegation/R19-VERIFICATION.md
- docs/saas-delegation/PROGRESS.md (ticket entry only)
- docs/saas-delegation/CLOSEOUT-PLAN.md (R19 row only)

No generated output or credential file is committed. Harnesses/snapshots/logs
remain untracked evidence. The separately owner-authorized external SaaS plan
file is synchronized byte-identically, without committing another checkout's branch.

Full suites, hosted CI/workflow execution, deployed migration/restore, live
provider behavior and staging are UNVERIFIED. The legacy Many CSV exporter still
uses its existing global get_current_user authorization and global lead query;
this ticket fixes formula escaping, not broader dashboard workspace isolation.
That existing authorization boundary needs a separately scoped review before
claiming the legacy dashboard is tenant-isolated. SaaS tenant A/B checks passed.
No push, merge, deploy, live/authenticated/paid call or production DB operation.
