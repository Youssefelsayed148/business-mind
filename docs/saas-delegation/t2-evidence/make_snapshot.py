"""Package only source needed for T2 validation, without environment files."""
from pathlib import Path
import subprocess
import zipfile

root = Path(__file__).resolve().parents[3]
tracked = subprocess.check_output(["git", "ls-files", "-z", "backend"], cwd=root)
names = [name.decode("utf-8") for name in tracked.split(b"\0") if name]
names += [
    "scripts/check_contract_copies.py",
    "scripts/test_check_contract_copies.py",
    "docs/saas-delegation/CONTRACT.sha256",
    "docs/saas-delegation/CONTRACT-V1.md",
    "docs/saas-delegation/CONTRACT-V1.1-DELTA.md",
    ".github/workflows/saas-delegation.yml",
]
with zipfile.ZipFile(Path(__file__).with_name("snapshot.zip"), "w", zipfile.ZIP_DEFLATED) as archive:
    for name in names:
        path = Path(name)
        if path.name.startswith(".env") or path.suffix not in {".py", ".json", ".toml", ".ini", ".mako", ".md", ".sha256", ".yml"}:
            continue
        archive.write(root / path, name)
print("T2 source snapshot created; no environment or credential files.")
