"""Explicitly reviewed uncommitted testing corrections, with byte provenance."""
import hashlib
import json
from pathlib import Path

base = Path('/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat')
paths = ['backend/app/models/__init__.py', 'backend/app/models/processed_webhook_event.py',
         'backend/tests/test_model_registry.py', 'scripts/test_canary_preflight.py']
manifest = []
for name in paths:
    data = (base / '.closeout-worktrees/batch-b' / name).read_bytes()
    target = Path('/var/tmp/many-closeout-t-20261028-02/source') / name
    target.write_bytes(data)
    manifest.append({'path': name, 'sha256': hashlib.sha256(data).hexdigest()})
(base / 'docs/saas-delegation/t-closeout-evidence/reviewed-fix-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
