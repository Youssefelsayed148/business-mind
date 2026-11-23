"""Reproduce the credential-free source archive used by run-tests.sh."""
from pathlib import Path
import subprocess
import zipfile

root = Path(__file__).resolve().parents[3]
names = subprocess.check_output(
    ["git", "ls-files", "-z", "backend", "scripts", "nginx/default.conf"], cwd=root,
).decode().split("\0")
names.append("backend/tests/test_forwarded_ip_trust.py")
with zipfile.ZipFile(Path(__file__).with_name("source.zip"), "w", zipfile.ZIP_DEFLATED) as archive:
    for name in dict.fromkeys(names):
        path = root / name
        if (name and path.is_file() and not path.name.startswith(".env")
                and path.suffix in {".py", ".json", ".ini", ".toml", ".mako", ".conf"}):
            archive.write(path, name)
print("Packaged source files only; environment/credential files excluded.")
