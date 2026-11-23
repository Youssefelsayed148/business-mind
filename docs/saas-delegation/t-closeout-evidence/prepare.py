"""Copy an allowlisted tracked source snapshot; never open env or token files."""
import hashlib
import json
from pathlib import Path
import subprocess

repo = Path('/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/.closeout-worktrees/batch-b')
evidence = Path(__file__).resolve().parent
scratch = Path('/var/tmp/many-closeout-t-20261028-02')
scratch.mkdir(exist_ok=False)
source = scratch / 'source'
allowed = {'.py', '.json', '.toml', '.ini', '.mako', '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.css', '.md', '.sha256', '.yaml', '.yml', '.txt'}
git = ['git', '--git-dir=/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/.git/worktrees/batch-b', f'--work-tree={repo}']
paths = subprocess.check_output(git + ['ls-files', '-z', 'backend', 'scripts', 'dashboard', 'docs/saas-delegation/CONTRACT-V1.md', 'docs/saas-delegation/CONTRACT-V1.1-DELTA.md', 'docs/saas-delegation/CONTRACT.sha256'], cwd=repo).decode().split('\0')
manifest = []
for name in sorted(filter(None, paths)):
    relative = Path(name)
    if any(part.startswith('.env') or part in {'node_modules', '__pycache__'} for part in relative.parts):
        continue
    if relative.suffix not in allowed or 'token' in relative.name.lower() and relative.suffix == '.txt':
        continue
    if relative.suffix == '.txt' and relative.name != 'requirements.txt':
        continue
    origin = repo / relative
    assert not origin.is_symlink(), name
    data = origin.read_bytes()
    target = source / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    manifest.append({'path': name, 'sha256': hashlib.sha256(data).hexdigest()})
result = {'source_sha': subprocess.check_output(git + ['rev-parse', 'HEAD'], cwd=repo).decode().strip(), 'files': manifest}
(evidence / 'source-manifest.json').write_text(json.dumps(result, indent=2) + '\n')
print(f'Snapshot: {result["source_sha"]}; {len(manifest)} allowlisted files; no overlays.')
