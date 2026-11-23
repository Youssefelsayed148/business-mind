import ast
import json
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET

repo = Path('/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat')
scratch = Path('/var/tmp/many-t0-20261028')
evidence = scratch / 'evidence'
destination = repo / 'docs/saas-delegation/t0-evidence'
destination.mkdir(exist_ok=True)

def cases(label):
    result = {}
    for case in ET.parse(evidence / f'{label}.xml').getroot().iter('testcase'):
        node = case.attrib['classname'].replace('.', '/') + '.py::' + case.attrib['name']
        problem = next(iter([*case.findall('failure'), *case.findall('error')]), None)
        result[node] = ('FAIL' if problem is not None else 'PASS', problem.attrib.get('message', '') if problem is not None else '')
    return result

before = cases('before-clean')
baseline = cases('baseline-before')
after = cases('after-full')
current_runs = json.loads((evidence / 'current-runs.json').read_text())
baseline_runs = json.loads((evidence / 'baseline-runs.json').read_text())
run_lookup = {(prefix, r['kind'], r['item']): r for prefix, runs in [('current', current_runs), ('baseline', baseline_runs)] for r in runs}
nodes = [node for node, (state, _) in before.items() if state == 'FAIL']
nodes += [node for node, (state, _) in baseline.items() if state == 'FAIL' and node not in nodes]

def details(node):
    if 'test_workspace_scoping' in node:
        return 'ENV/ISOLATION', 'Shared login-IP quota: 429 in suite; module and test pass after FLUSHALL. Limiter introduced by f92dcfc.', 'Autouse disable + explicit rate_limit marker', 'Y'
    if 'test_campaign_routes' in node or 'test_disconnect' in node or 'test_reconnect_restores' in node:
        return 'STALE', 'Fixture uses role=user; f92dcfc roles.py:11 maps user to viewer, which lacks the required mutation permission. 403 persists alone.', 'Use an authorized role while retaining workflow assertions; broader fixture repair left for approval', 'N'
    if 'test_create_campaign_with_keywords' in node:
        return 'ENV/ISOLATION', 'Asserts first keyword=prompt, but f92dcfc Campaign.keywords has no order_by. Query returns ai first here; not evidence of incorrect keyword membership.', 'Compare keyword set; no behavior-changing commit found, so outside stale-assertion-only fixes', 'N'
    if 'test_any_media_and_specific_media_matching' in node:
        return 'STALE', 'b5c0b54 rejects URL-only specific_media at schema construction; old test constructs and activates it.', 'Assert URL-only validation error; retain valid media matching checks', 'Y'
    if 'test_instagram_token_refresh' in node:
        return 'ENV/ISOLATION', 'b7675a3 added _make_token with Workspace and InstagramAccount pending in the same flush, without ORM relationship or explicit parent flush; workspace FK fails before token behavior runs.', 'Explicitly flush parent Workspace; outside authorized stale-assertion-only changes', 'N'
    if 'test_message_retry' in node:
        return 'ENV/ISOLATION', 'Random lead_id has no Lead row; f92dcfc introduced the FK, retained at Message.lead_id. IntegrityError precedes endpoint/login. Also uses obsolete role and patch target.', 'Seed real Instagram Lead, authorized role, and patch source task; leave assertions intact; broader fixture repair needs approval', 'N'
    if 'test_meta_integration' in node:
        return 'ENV/ISOLATION', 'f92dcfc registers /meta/connect/mock only when APP_ENV=development. Required APP_ENV=test makes route 404; second test then dereferences missing account.', 'Test dev-only route in an isolated app import or test encryption service directly; do not weaken endpoint or switch APP_ENV', 'N'
    if 'test_send_private_reply' in node:
        return 'ENV/ISOLATION', 'Worker _get_db opens SessionLocal (f92dcfc); fixture commits inside an uncommitted outer connection transaction. Worker cannot see Message; captured log says Message not found for send.', 'Bind worker session to test connection without closing/rolling back fixture; broader fixture repair needs approval', 'N'
    if 'test_webhook_processing' in node:
        return 'ENV/ISOLATION', 'f92dcfc route enqueues .delay; no worker consumes it in these tests. Duplicate insert additionally db.rollback()s shared outer fixture transaction, causing ObjectDeletedError.', 'Explicitly execute worker with isolated test session; test dedupe without rolling back seeded outer transaction; broader fixture repair needs approval', 'N'
    if 'test_0019_defaults_constraints_and_round_trip' in node:
        return 'STALE', '2ead0ea introduced head 0027; test still asserted 0026 from c440a00. Baseline expects 0022 and passes. Fixture strips 0019 columns before upgrading.', 'Resolve the single actual head via existing alembic subprocess helper', 'Y'
    if 'old_file_is_unchanged' in node:
        return 'STALE', 'Baseline hardcodes beat_schedule.py SHA. b7675a3 already removed the obsolete checksum assertion and retained the four WhatsApp schedule entries on this branch.', 'Already fixed before T0 by b7675a3; no new edit', 'N (already fixed)'
    raise ValueError(node)

lines = [
    '# T0 failure inventory — 2026-10-28', '',
    'Observed HEAD: `1891f89`; untouched baseline: `5cc60c7`. The historical 29-item FAILED/ERROR list was not saved in PROGRESS.md, so its exact membership cannot be reconstructed honestly. This inventory includes **all 35 current full-run failures**, the one additional baseline failure, and both historically reported migration modules below. No historical item is silently assumed reproduced.', '',
    'Every current full-run failure was rerun as a module and individually; the baseline full-run failures received the same treatment. All runs use fresh Redis. PASS/FAIL in module/single columns describes the named test, not whether other tests in that module failed. Full logs and XML are in `runs.zip`; exact expanded commands/outcomes are in `current-runs.json`, `baseline-runs.json`, and PROGRESS.md.', '',
    '| # | module::test | Class | Module / single | Baseline full / single | Evidence | Proposed fix | Applied |',
    '|---|---|---|---|---|---|---|---|',
]
for index, node in enumerate(nodes, 1):
    classification, detail, proposed, applied = details(node)
    statuses = []
    for kind, item in [('module', node.split('::')[0]), ('single', node)]:
        run = run_lookup.get(('current', kind, item))
        statuses.append(cases(run['label']).get(node, ('ABSENT', ''))[0] if run else 'ABSENT')
    run = run_lookup.get(('baseline', 'single', node))
    baseline_single = cases(run['label']).get(node, ('ABSENT', ''))[0] if run else 'ABSENT'
    if 'test_0019_defaults_constraints_and_round_trip' in node:
        baseline_single = cases('migration-0019-baseline-single')[node][0]
    baseline_full = baseline.get(node, ('ABSENT', ''))[0]
    path, name = node.split('::')
    source = scratch / 'current/backend' / path
    if not source.exists() or name not in source.read_text():
        source = scratch / 'baseline/backend' / path
    tree = ast.parse(source.read_text())
    func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    link = f'../../../backend/{path}:{func.lineno}'
    if 'old_file_is_unchanged' in node:
        link = '../../../backend/tests/test_whatsapp_tasks.py:657'
    lines.append(f'| {index} | [{node}]({link}) | {classification} | {" / ".join(statuses)} | {baseline_full} / {baseline_single} | {detail} | {proposed} | {applied} |')

lines += ['', '## Separate migration bug and historical errors', '',
    '| module / operation | Class | Evidence | Proposed fix | Applied |',
    '|---|---|---|---|---|',
    '| test_whatsapp_outreach_migration | Historical error NOT reproduced | Current/baseline full suite and isolated module pass. Fixture upgrades only to 0017, strips modern columns, then tests 0018; it does not follow an unmodified empty DB all the way to head. | No change to passing test. | N |',
    '| test_whatsapp_outreach_settings_migration::test_0019_defaults_constraints_and_round_trip | Historical setup error NOT reproduced; current STALE assertion above | Fixture upgrades only to 0018 then strips 0019 columns. Current run reaches head and fails on old head string; baseline passes. | Head assertion updated only. | Y (assertion) |',
    '| Empty DB: alembic upgrade head (current and baseline) | REAL BUG | Both independently fail with DuplicateColumn ctwa_counts_as_consent in 0019. 0001_initial.py:20 creates current Base.metadata (f92dcfc); 0019_whatsapp_outreach_settings.py:20 adds columns unconditionally (968e43d). | Idempotent column/constraint guards; proposal below. | N |', '',
    'No separate test-order-dependent failure was established beyond Redis quota pollution, classified ENV/ISOLATION because the shared external state is proven. The unordered keyword assertion depends on database row ordering; it is not evidence of dependence on another test.', '',
    '## Migration proposal — NOT APPLIED', '',
    'Keep revision ids and chain intact. Inspect existing columns/constraints in 0019 before adding them (or use ADD COLUMN IF NOT EXISTS where appropriate); add only missing objects. Verify an existing object has the expected type/default/nullability/constraint expression and fail on incompatibility rather than silently accepting drift. A correctly shaped existing DB must receive no schema/data change. Do not replace 0001 with a new schema snapshot in T0. Validate empty-to-head, real 0018-to-head, current DB no-op, and downgrade/upgrade in disposable databases before approval.', '',
    'Risk: IF NOT EXISTS alone can conceal schema drift; inspection can become stale after DDL unless refreshed; downgrade can remove columns originally created by create_all rather than this migration. Later unconditional migrations may surface after 0019 is guarded. Migration files were not edited; safety and complete-chain success remain UNVERIFIED.', '',
    '## Canary paths', '',
    '- Webhook processing: all six failing test_webhook_processing cases above sit on this path, but their current failures are harness/session/async assumptions. test_webhook_event_enqueues_processing passes. Duplicate rollback is an additional isolation problem.',
    '- Message retry: all three test_message_retry cases fail during invalid FK seed insertion, before the retry endpoint; no successful retry canary conclusion can be drawn from them. The four private-reply send cases similarly never see the seeded Message in the worker session.',
    '- WhatsApp send: current test_whatsapp_tasks and test_whatsapp_phase5 have no failures in the full run or combined clean run. See isolated module outcomes in PROGRESS.md. The baseline-only beat checksum failure is schedule bookkeeping rather than send execution.', '',
    '## Limits', '',
    'The eight token-refresh failures cannot be confirmed pre-existing at 5cc60c7: that test module and feature do not exist there. They were introduced with b7675a3 and all fail alone on their fixture precondition. The stale 0026 head expectation was introduced after baseline and invalidated by 2ead0ea. Therefore the earlier F-10 claim that every branch failure is present at baseline does not describe this HEAD.',
    '',
    'History limitation: f92dcfc is the root commit of this repository and already contains the RBAC mapping, development-only mock route, async webhook route, independent worker session, and their inconsistent tests. Pickaxe/blame cannot establish an earlier behavioral transition for those cases. STALE on the six RBAC cases means their expected success contradicts the explicit current permission model; it does not claim an unavailable pre-root commit was inspected.',
]
(destination / 'FAILURES.md').write_text('\n'.join(lines) + '\n')
for prefix in ['current', 'baseline']:
    shutil.copy2(evidence / f'{prefix}-runs.json', destination)
shutil.copy2(evidence / 'history.json', destination)
for label in ['before-clean', 'baseline-before', 'after-full']:
    text = (evidence / f'{label}.log').read_text()
    selected = [line for line in text.splitlines() if line.startswith(('FAILED ', 'ERROR ')) or re.match(r'^\d+ (failed|passed)', line)]
    (destination / f'{label}-summary.txt').write_text('\n'.join(selected) + '\n')
shutil.make_archive(str(destination / 'runs'), 'zip', evidence)
print(f'Wrote inventory for {len(nodes)} unique full-run failures to {destination}')
