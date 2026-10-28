"""Package current tracked backend code without environment or credential files."""
from pathlib import Path
import subprocess
import zipfile

root = Path(__file__).resolve().parents[3]
paths = subprocess.check_output(["git", "ls-files", "-z", "backend", "scripts/preflight_prod.py"], cwd=root)
with zipfile.ZipFile(Path(__file__).with_name("snapshot.zip"), "w", zipfile.ZIP_DEFLATED) as archive:
    for raw in paths.split(b"\0"):
        if not raw:
            continue
        relative = raw.decode("utf-8")
        path = Path(relative)
        if path.name.startswith(".env") or path.suffix not in {".py", ".json", ".toml", ".ini", ".mako"}:
            continue
        archive.write(root / path, relative)
print("Packaged tracked backend source and current contract fixture; no environment files.")
