"""Update only the authorized closeout documents and synchronized plan copy."""
from pathlib import Path
import hashlib

root = Path(__file__).resolve().parents[3]
plan = root / 'docs/saas-delegation/CLOSEOUT-PLAN.md'
other = Path('/mnt/d/Projects/Work Projects/The Osiris Labs/SAAS-chats-ai/implementation/CLOSEOUT-PLAN.md')
original = plan.read_bytes()
assert other.read_bytes() == original, 'Plan copies diverged; preserve both for review'
text = original.decode('utf-8')
rows = {
'R1': '[x] Many local identity/account-erasure integration verified: 31 account-erasure, 15 OAuth and 2 real migration tests pass in the 1007-pass full suite. Scoped callbacks also pass (32 compliance tests). Staging and unresolved-identity operator remediation remain UNVERIFIED (many-full-test-evidence)',
'R2': '[x] Many local A16 producer and hashed dedupe verified in the full suite: 26 contact-erasure, 8 processed-event service and 1 migration tests pass. SaaS receiver/full/live round trip remains UNVERIFIED by this Many-only run; in-flight quiescence remains required (many-full-test-evidence)',
'R3': '[x] Many local policy source passes full dashboard TypeScript and lint checks (one existing hook warning). Owner publication review and SaaS verification remain pending; no publication authorization (many-full-test-evidence)',
'R9': '[x] Current 0030 rehearsals pass: empty-to-head, 0022-to-head, each downgrade to 0029/re-upgrade, clean alembic check; exactly one head 0030_meta_account_erasure. Legacy downgrade-to-base is outside this gate and has a missing-index limitation (many-full-test-evidence)',
'R10': '[x] Fresh final source snapshot: 1007 backend passed, 0 failed/errors/skipped; scripts 29 passed, contract hashes OK; dashboard tsc/lint pass. Fixture now uses actual Alembic upgrades; all earlier failed/interrupted attempts retained and explained (many-full-test-evidence)',
'R12': '[ ] D5 remains OPEN per current owner testing instruction; commit 59d3442 preserved and no Instagram dispatch/send edits. All 13 unsupported-Instagram tests pass in the final full suite (many-full-test-evidence)',
'R17': '[x] Many local policy/review consistency and dashboard checks verified; full suite green. Owner publication, nine D4 recordings and live Meta evidence remain UNVERIFIED (many-full-test-evidence)',
'R19': '[x] Many local full verification: all 15 CSV tests pass (14 export/security cases plus import), model registry passes, actual migration drift clean, dashboard checks pass. SaaS, hosted CI and provider-global webhook health remain outside this run (many-full-test-evidence)',
}
lines = []
for line in text.splitlines(keepends=True):
    for key, replacement in rows.items():
        if line.startswith(f'| {key} |'):
            columns = line.rstrip('\r\n').split('|')
            columns[3] = ' ' + replacement + ' '
            line = '|'.join(columns) + ('\r\n' if line.endswith('\r\n') else '\n')
            break
    if line.startswith('| D5 |'):
        line = '| D5 | Instagram unsupported-message forwarding for delegated accounts (`59d3442`) | OPEN per current owner testing instruction (2026-10-29); preserve implementation; 13 full-suite tests pass |\n'
    if line.startswith('- A8 [x] D5'):
        line = '- A8 [ ] D5 remains OPEN per current testing instruction; keep commit `59d3442` unchanged. Its 13 tests pass in the final full suite.\n'
    if line.startswith('Gate A: D5 owner decision is resolved'):
        line = 'Gate A: local Many tests and requested migration rehearsals are green (many-full-test-evidence). D5 remains OPEN per current instruction; no release/owner approval is inferred.\n'
    if line.startswith('- [ ] `backend/tests/test_saas_unsupported_instagram.py`'):
        line = '- [x] `backend/tests/test_saas_unsupported_instagram.py`: 13 passed in the final 1007-pass suite; JUnit and named-file counts in many-full-test-evidence. D5 stays OPEN.\n'
    lines.append(line)
text = ''.join(lines) + '''

## Many full-test closeout - 2026-10-29

This current testing instruction supersedes older D5 confirmed/resolved wording:
D5 stays OPEN; 59d3442 is retained without this session changing Instagram handlers.
Tested HEAD f8e9aa70b3fbb0a2af7bd8cff0db3f73f1338f84 plus the reviewed test-fixture
diff recorded in the fresh 383-file source manifest. Full backend: 1007 passed,
0 failed/errors/skipped (153.02 s). Scripts: 29 passed (0.991 s), contracts OK.
Locked-cache dashboard TypeScript and lint exit 0; one pre-existing hook warning.
Both requested migration paths and 0030-to-0029 roundtrips/drift pass, one head.
R1/R2/R3/R17/R19 checkmarks cover the stated Many local evidence only, never live,
SaaS receiver, publication, operator remediation or release gates. Initial harness
errors, interrupted run, rejected teardown approach and the legacy base-downgrade
missing-index limitation are preserved in many-full-test-evidence/README.md.
No push, merge, deployment, external authenticated/paid call or live send.
'''
data = text.encode('utf-8')
plan.write_bytes(data)
other.write_bytes(data)
assert plan.read_bytes() == other.read_bytes()
print('Synchronized plan SHA256=' + hashlib.sha256(data).hexdigest())
progress = root / 'docs/saas-delegation/PROGRESS.md'
with progress.open('a', encoding='utf-8', newline='') as output:
    output.write('''

## Many full-test closeout - 2026-10-29

Verified initial clean Windows Git status, closeout/batch-b,
HEAD f8e9aa70b3fbb0a2af7bd8cff0db3f73f1338f84. Read CLAUDE, handoff, plan and
release gates. Current owner instruction supersedes historic D5 confirmation:
D5 remains OPEN; 59d3442 is retained, no Instagram dispatch/send code changed.

Fresh allowlisted 383-file snapshots, new private PostgreSQL 18 clusters using
Unix sockets (listen_addresses empty), private Redis and loopback-only namespace,
env -i and dummy secrets. No old source snapshot used. No env/credential/token
or backup files copied into snapshots. Every test command has explicit test
environment and a current_database assertion. PostgreSQL/Redis started by each
run were stopped; evidence includes teardown records.

Final backend: 1007 passed, 0 failed, 0 errors, 0 skipped, 58 warnings,
153.02 s pytest / 154.315 s command wall time. Scripts: 29 passed, no failures,
errors/skips, 0.991 s unittest / 1.121 s wall. Contracts: 3 hashes OK, exit 0.
Locked dashboard dependency tree, TypeScript (--incremental false) and full lint:
exit 0 each; lint retains one existing missing-toast-dependency warning.
Actual empty-to-0030 and 0022-to-0030, both 0030-to-0029/re-upgrade roundtrips,
and both alembic checks pass; one head 0030_meta_account_erasure.

Named final-suite passes: account erasure 31; R1 OAuth 15; R1 migration 2;
callbacks/compliance 32; A16 contact erasure 26; hashed dedupe service 8 and
migration 1; unsupported Instagram 13; Graph versions 32; CSV 15 including all
14 export/security cases. These are subsets, not extra suite totals.

Only test-fixture behavior changed: real Alembic upgrade replaces create_all;
dispose connections at teardown and let the harness own its disposable database,
preserving Alembic revision/schema consistency across sessions. Two consecutive
model sessions pass 3/3 each. Final manifest hashes match current source.
No authorization, tenancy, dedupe, erasure or assertions were weakened.

Earlier failures are retained, not omitted: initial harness module invocation
caused 1007 setup errors (local alembic shadows installed module); corrected to
the console entrypoint. Next full attempt was interrupted at -15 after discovering
drop_all left the revision at head; its progress log has no completed-suite/JUnit
claim. A rejected downgrade-to-base teardown yielded 3 passed plus 1 teardown
error: the legacy path drops missing ix_conversations_instagram_account_id.
That optional path is outside the requested 0030/0029 rehearsal; it remains a
documented limitation, not a claim of working base rollback. Final fixture cleanup
uses engine.dispose, with cluster lifecycle managed by the owning harness.

Exact commands, exits, durations, source hashes, failed/interrupted attempt logs,
final JUnit and converted script JUnit: many-full-test-evidence/README.md,
commands.json, counts.json, source-manifest.json and attempt-1/attempt-2/attempt-3.
No new test reruns were used to produce reports. Only conftest differs between
earlier passing dashboard/script/migration snapshots and final source; those
checks' application/configuration/script files are byte-identical.

Updated evidence-backed local R9/R10/R1/R2/R3/R17/R19 backlog statements; SaaS
implementation/CLOSEOUT-PLAN.md synchronized byte-for-byte under the plan-only
exception. No SaaS application/source changes or SaaS test claims by this run.
UNVERIFIED: live Meta/Graph compatibility, staging/canary, operator remediation,
deployment/hosted CI, real SaaS round trip, publication/recordings and release
approval. D5 OPEN. No push, merge, deploy, authenticated external/paid call or send.
''')
