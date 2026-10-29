from pathlib import Path
import hashlib
import json

base = Path('/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat')
name = 'nginx/default.conf'
data = (base / '.closeout-worktrees/batch-b' / name).read_bytes()
target = Path('/var/tmp/many-closeout-t-20261028-02/source') / name
target.parent.mkdir(parents=True, exist_ok=True)
target.write_bytes(data)
path = base / 'docs/saas-delegation/t-closeout-evidence/source-manifest.json'
manifest = json.loads(path.read_text())
manifest['files'].append({'path': name, 'sha256': hashlib.sha256(data).hexdigest()})
path.write_text(json.dumps(manifest, indent=2) + '\n')
print('Added explicit nginx source fixture before canary checks.')
