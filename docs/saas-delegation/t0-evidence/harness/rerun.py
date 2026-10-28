"""Reproduce every full-run failure with a fresh Redis for each invocation."""
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

scratch = Path('/var/tmp/many-t0-20261028')
evidence = scratch / 'evidence'
harness = Path(__file__).with_name('run.sh')
target, source, prefix = sys.argv[1:]
root = ET.parse(evidence / f'{source}.xml').getroot()
nodes = []
for case in root.iter('testcase'):
    if case.find('failure') is None and case.find('error') is None:
        continue
    classname = case.attrib['classname'].split('.')
    # These suites use module-level functions, not test classes.
    assert len(classname) == 2 and classname[0] == 'tests', classname
    node = f"tests/{classname[1]}.py::{case.attrib['name']}"
    if node not in nodes:
        nodes.append(node)
(evidence / f'{prefix}-nodes.json').write_text(json.dumps(nodes, indent=2))
modules = list(dict.fromkeys(node.split('::')[0] for node in nodes))
results = []
for kind, items in [('module', modules), ('single', nodes)]:
    for index, item in enumerate(items):
        label = f'{prefix}-{kind}-{index:02}'
        command = ['bash', str(harness), target, label, item, '-q']
        print('COMMAND ' + json.dumps(command), flush=True)
        result = subprocess.run(command, capture_output=True, text=True)
        print(result.stdout[-12000:], flush=True)
        if result.stderr:
            print(result.stderr, flush=True)
        results.append(dict(kind=kind, item=item, label=label, command=command, exit_code=result.returncode))
        (evidence / f'{prefix}-runs.json').write_text(json.dumps(results, indent=2))
        print(f'RUN_COMPLETE {label} EXIT={result.returncode}', flush=True)
