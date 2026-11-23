"""Fresh tracked-source allowlist plus explicit reviewed untracked regression."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

base = Path('/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat')
repo = base / '.closeout-worktrees/batch-b'
evidence = Path(__file__).resolve().parent
source = Path('/var/tmp/many-closeout-a5-20261028-01/source')
source.mkdir(parents=True, exist_ok=False)
git = ['git', f'--git-dir={base}/.git/worktrees/batch-b', f'--work-tree={repo}']
paths = subprocess.check_output(git + ['ls-files', '-z', 'backend', 'scripts', 'dashboard', 'docs', 'nginx', '.github', 'README.md', '.env.example', '.env.production.example'], cwd=repo).decode().split('\0')
paths += ['backend/tests/test_model_registry.py', 'backend/tests/test_meta_graph_version.py']
allowed = {'.py', '.json', '.toml', '.ini', '.mako', '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.css', '.md', '.sha256', '.yaml', '.yml', '.conf'}
manifest, pins = [], []
for name in sorted(set(filter(None, paths))):
    path = Path(name)
    template = name in {'.env.example', '.env.production.example'}
    if any(part.endswith('-evidence') or part in {'node_modules', '__pycache__'} for part in path.parts):
        continue
    if not template and (any(part.startswith('.env') for part in path.parts) or path.suffix not in allowed):
        continue
    origin = repo / path
    assert not origin.is_symlink(), name
    data = origin.read_bytes()
    # Templates are inspected for the approved default assertion only, not copied.
    if template:
        assert b'META_GRAPH_API_VERSION=v26.0' in data
        pins.append({'path': name, 'review': 'placeholder template uses v26.0'})
        continue
    target = source / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    manifest.append({'path': name, 'sha256': hashlib.sha256(data).hexdigest()})
    for number, line in enumerate(data.decode('utf-8-sig').splitlines(), 1):
        if re.search(r'\bv\d{1,2}\.0\b|graph\.instagram\.com', line):
            pins.append({'path': name, 'line': number, 'text': line})
(evidence / 'source-manifest.json').write_text(json.dumps({'base_sha': subprocess.check_output(git + ['rev-parse', 'HEAD'], cwd=repo).decode().strip(), 'reviewed_uncommitted_changes': subprocess.check_output(git + ['diff', '--name-only'], cwd=repo).decode().splitlines() + ['backend/tests/test_model_registry.py', 'backend/tests/test_meta_graph_version.py'], 'files': manifest}, indent=2) + '\n')
(evidence / 'version-audit.json').write_text(json.dumps(pins, indent=2) + '\n')
print(f'Fresh A5 snapshot: {len(manifest)} source files; version audit retained; templates verified only.')
