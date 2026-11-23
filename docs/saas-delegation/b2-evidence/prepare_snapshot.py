"""Prepare B2 source plus approved companion overlays; never include env/credential files."""
from pathlib import Path
import subprocess
import zipfile

root = Path(__file__).resolve().parents[3]
out = Path(__file__).parent
paths = subprocess.check_output(["git", "ls-files", "-z", "backend", "scripts/preflight_prod.py"], cwd=root).decode().split("\0")
paths += ["backend/tests/test_processed_event_service.py", "backend/tests/test_processed_event_migration.py", "backend/alembic/versions/0029_hash_processed_event_keys.py", "backend/alembic/versions/0028_meta_compliance.py", "backend/tests/test_contact_erasure.py", "backend/tests/test_webhook_retention.py", "backend/app/services/contact_erasure.py", "backend/app/api/routes_contact_erasure.py"]
with zipfile.ZipFile(out / "snapshot.zip", "w", zipfile.ZIP_DEFLATED) as archive:
    for name in paths:
        path = Path(name)
        if name and not path.name.startswith(".env") and path.suffix in {".py", ".json", ".toml", ".ini", ".mako"}:
            source = root / path
            if name == "backend/tests/conftest.py":
                source = out / "a3-conftest.py"
            if name == "backend/alembic/versions/0019_whatsapp_outreach_settings.py":
                source = out / "a2-0019-overlay.py"
            if name == "backend/alembic/versions/0028_meta_compliance.py":
                source = out / "b1-0028-overlay.py"
            archive.write(source, name)
print("Packaged B2 source-only snapshot with reviewed A2/A3/B1 overlays; no environment/credential files.")
