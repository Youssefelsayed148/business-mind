"""Check LF-normalised SHA256 hashes of the three frozen SaaS contract copies.

Usage: python scripts/check_contract_copies.py [--root DIR]
Uses only the standard library; never imports the application or uses the network.
"""

import argparse
import hashlib
from pathlib import Path
import re
import sys

MANIFEST = "docs/saas-delegation/CONTRACT.sha256"
CONTRACT_FILES = (
    "docs/saas-delegation/CONTRACT-V1.md",
    "docs/saas-delegation/CONTRACT-V1.1-DELTA.md",
    "backend/tests/fixtures/contract/signing_vectors.json",
)


def check(root: Path) -> list[str]:
    problems: list[str] = []
    try:
        manifest = (root / MANIFEST).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return [f"{MANIFEST}: cannot read manifest ({exc})"]

    expected: dict[str, str] = {}
    for number, line in enumerate(manifest.splitlines(), 1):
        if not line.strip() or line.startswith(("source:", "#")):
            continue
        match = re.fullmatch(r"([0-9a-fA-F]{64})  (.+)", line)
        if match is None:
            problems.append(f"{MANIFEST}:{number}: invalid SHA256 entry")
            continue
        digest, name = match.groups()
        if name not in CONTRACT_FILES:
            problems.append(f"{MANIFEST}:{number}: unexpected file {name}")
        elif name in expected:
            problems.append(f"{MANIFEST}:{number}: duplicate file {name}")
        else:
            expected[name] = digest.lower()

    for name in CONTRACT_FILES:
        if name not in expected:
            problems.append(f"{name}: missing SHA256 entry in {MANIFEST}")
            continue
        try:
            data = (root / name).read_bytes().replace(b"\r\n", b"\n")
        except OSError as exc:
            problems.append(f"{name}: cannot read file ({exc})")
            continue
        if hashlib.sha256(data).hexdigest() != expected[name]:
            problems.append(f"{name}: SHA256 mismatch")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    problems = check(args.root)
    for problem in problems:
        print(f"contract copies: {problem}", file=sys.stderr)
    if not problems:
        print("contract copies OK (3 LF-normalised SHA256 hashes)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
