"""Prepare tracked source plus Group 1 tests; never include env/credential files."""
from pathlib import Path
import subprocess
import zipfile

root = Path(__file__).resolve().parents[3]
out = Path(__file__).parent
paths = subprocess.check_output(["git", "ls-files", "-z", "backend", "scripts/preflight_prod.py"], cwd=root).decode().split("\0")
paths += ["backend/tests/test_closeout_migrations.py", "backend/tests/test_instagram_hard_delete.py"]
with zipfile.ZipFile(out / "snapshot.zip", "w", zipfile.ZIP_DEFLATED) as archive:
    for name in paths:
        path = Path(name)
        if name and not path.name.startswith(".env") and path.suffix in {".py", ".json", ".toml", ".ini", ".mako"}:
            archive.write(root / path, name)
print("Packaged source-only snapshot; environment and credential files excluded.")
