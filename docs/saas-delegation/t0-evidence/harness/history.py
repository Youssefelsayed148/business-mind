"""Capture exact pickaxe/blame commands for every isolated failure."""
import ast
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

repo = Path('/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat')
scratch = Path('/var/tmp/many-t0-20261028')
results = []
for prefix, revision in [('current', 'HEAD'), ('baseline', '5cc60c7')]:
    runs = json.loads((scratch / 'evidence' / f'{prefix}-runs.json').read_text())
    for run in runs:
        if run['kind'] != 'single' or not run['exit_code']:
            continue
        path, name = run['item'].split('::')
        relative = 'backend/' + path
        source = subprocess.check_output(['git', '-c', f'safe.directory={repo}', '-C', str(repo), 'show', f'{revision}:{relative}'], text=True)
        tree = ast.parse(source)
        function = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
        asserts = [n for n in ast.walk(function) if isinstance(n, ast.Assert)]
        asserted = ast.get_source_segment(source, asserts[-1]) if asserts else name
        commands = [
            ['git', 'log', revision, '--oneline', '-S', asserted, '--', relative],
            ['git', 'blame', revision, '-L', f'{function.lineno},{function.end_lineno}', '--', relative],
        ]
        item = dict(test=run['item'], revision=revision, asserted_string=asserted, commands=[])
        for command in commands:
            actual = ['git', '-c', f'safe.directory={repo}', '-C', str(repo), *command[1:]]
            completed = subprocess.run(actual, capture_output=True, text=True)
            item['commands'].append(dict(command=command, exit_code=completed.returncode, output=completed.stdout, stderr=completed.stderr))
        results.append(item)
(scratch / 'evidence' / 'history.json').write_text(json.dumps(results, indent=2))
print(f'Captured pickaxe and blame for {len(results)} isolated failure/revision pairs')
