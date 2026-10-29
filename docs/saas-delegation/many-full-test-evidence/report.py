"""Derive counts from retained artifacts without rerunning any test."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

here = Path(__file__).resolve().parent
root = here.parents[2]
report = {'attempts': {}, 'specific_backend_files': {}}
for directory in [here / 'attempt-1', here / 'attempt-2', here / 'attempt-3', here]:
    if not directory.exists():
        continue
    data = []
    for path in sorted(directory.glob('*.xml')):
        suites = ET.parse(path).getroot()
        counts = Counter()
        for case in suites.iter('testcase'):
            outcome = 'error' if case.find('error') is not None else 'fail' if case.find('failure') is not None else 'skip' if case.find('skipped') is not None else 'pass'
            counts[outcome] += 1
            if directory == here and path.name == 'many-backend.xml':
                file = case.get('classname', '')
                report['specific_backend_files'].setdefault(file, Counter())[outcome] += 1
        data.append({'artifact': path.name, 'counts': dict(counts), 'suites': [dict(s.attrib) for s in suites.iter('testsuite')]})
    report['attempts'][directory.name] = data
    for entry in data:
        log = directory / entry['artifact'].replace('many-backend.xml', 'backend.log').replace('.xml', '.log')
        if log.exists():
            entry['pytest_summary'] = [line for line in log.read_text().splitlines() if re.search(r'\d+ (?:passed|errors?|failed).* in ', line)][-1:]

manifest = json.loads((here / 'source-manifest.json').read_text())
changed = []
for entry in manifest['files']:
    if hashlib.sha256((root / entry['path']).read_bytes()).hexdigest() != entry['sha256']:
        changed.append(entry['path'])
report['snapshot_matches_current_source'] = not changed
report['source_changes_after_snapshot'] = changed
report['tested_head'] = manifest['head']
report['earlier_snapshot_differences'] = {}
for directory in ('attempt-1', 'attempt-2', 'attempt-3'):
    earlier = json.loads((here / directory / 'source-manifest.json').read_text())
    old = {entry['path']: entry['sha256'] for entry in earlier['files']}
    report['earlier_snapshot_differences'][directory] = [entry['path'] for entry in manifest['files'] if old.get(entry['path']) != entry['sha256']]
progress = Counter()
for line in (here / 'attempt-2/backend.log').read_text().splitlines():
    match = re.fullmatch(r'([.FE]+)(?:\s+\[\s*\d+%\])?', line)
    if match:
        progress.update(match.group(1))
report['interrupted_run_observed_progress_only'] = dict(progress)
script_log = (here / 'attempt-1/scripts.log').read_text()
script_cases = re.findall(r'^(test_\S+) \(([^)]+)\) \.\.\. ok$', script_log, re.MULTILINE)
assert len(script_cases) == 29 and 'OK' in script_log
suite = ET.Element('testsuite', name='unittest scripts (converted from original verbose log)', tests='29', failures='0', errors='0', skipped='0', time='0.991')
for name, classname in script_cases:
    ET.SubElement(suite, 'testcase', name=name, classname=classname)
ET.ElementTree(suite).write(here / 'scripts-junit.xml', encoding='utf-8', xml_declaration=True)
report['scripts'] = {'pass': 29, 'fail': 0, 'error': 0, 'skip': 0, 'seconds': .991, 'junit': 'Converted from original unittest log; no rerun'}
(here / 'counts.json').write_text(json.dumps(report, indent=2))
print(json.dumps({key: value for key, value in report.items() if key != 'specific_backend_files'}, indent=2))
for name, counts in report['specific_backend_files'].items():
    if any(term in name for term in ('erasure', 'meta_compliance', 'r1_oauth', 'processed_event', 'unsupported_instagram', 'meta_graph_version', 'r19_csv')):
        print(name, dict(counts))
