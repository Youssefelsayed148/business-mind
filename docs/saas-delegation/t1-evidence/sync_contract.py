"""Copy only the three pinned public contract artifacts; never modify the source."""
import difflib
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT.parent / "SAAS-chats-ai-phase6"
COMMIT = "5fa72f7165ea0fc1dacd659e03e211341334ab32"
FILES = [
    ("implementation/PHASE-06-V2/many-pack/CONTRACT-V1.md", "docs/saas-delegation/CONTRACT-V1.md"),
    ("implementation/PHASE-06-V2/CONTRACT-V1.1-DELTA.md", "docs/saas-delegation/CONTRACT-V1.1-DELTA.md"),
    ("apps/api/tests/fixtures/contract/signing_vectors.json", "backend/tests/fixtures/contract/signing_vectors.json"),
]


def git(*args):
    return subprocess.check_output(["git", "-C", str(SOURCE), *args])


def lf(data):
    return data.replace(b"\r\n", b"\n")


assert git("rev-parse", "HEAD").decode().strip() == COMMIT
assert git("branch", "--show-current").decode().strip() == "feature/phase-6-channels"
hashes = []
for source, target in FILES:
    original = (SOURCE / source).read_bytes()
    assert lf(original) == lf(git("show", f"{COMMIT}:{source}")), source
    destination = ROOT / target
    if target.endswith(".json"):
        old = json.loads(destination.read_bytes())["vectors"]
        new = json.loads(original)["vectors"]
        assert [{k: v for k, v in x.items() if k != "name"} for x in old] == [
            {k: v for k, v in x.items() if k != "name"} for x in new
        ]
    destination.write_bytes(original)
    normalized = lf(destination.read_bytes())
    difference = "".join(difflib.unified_diff(
        lf(original).decode("utf-8").splitlines(keepends=True),
        normalized.decode("utf-8").splitlines(keepends=True),
        fromfile=source, tofile=target,
    ))
    print(f"LF-normalized diff: {target}\nBEGIN DIFF\n{difference}END DIFF")
    assert not difference
    assert normalized == lf(original)
    hashes.append(f"{hashlib.sha256(normalized).hexdigest()}  {target}")
manifest = "source: SaaS repo, commit 5fa72f7\n" + "\n".join(hashes) + "\n"
(ROOT / "docs/saas-delegation/CONTRACT.sha256").write_bytes(manifest.encode("utf-8"))
print(manifest, end="")
print("Vector test ids use v['name'] dynamically; no test source edits needed.")
