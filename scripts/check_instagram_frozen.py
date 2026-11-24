#!/usr/bin/env python3
"""Fail if any frozen Instagram file differs from the base ref (default origin/main).

Instagram receive/dispatch/send code is frozen (CLAUDE.md rule 3). This compares
the working tree, staged and committed changes against the base, so a committed
edit, a staged edit, an unstaged edit and a deletion all fail. Stdlib only.

    python scripts/check_instagram_frozen.py [--base origin/main] [--root DIR]

Exit 0 clean, 1 a frozen file changed or is missing, 2 the base ref cannot be read.
"""
import argparse
import subprocess
import sys
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parent.parent
FROZEN_FILES = (
    "backend/app/api/routes_instagram.py",
    "backend/app/api/routes_webhooks.py",
    "backend/app/workers/instagram_token_tasks.py",
    "backend/app/workers/instagram_token_beat_schedule.py",
    "backend/app/models/instagram_account.py",
)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    root: Path = args.root

    if _git(root, "rev-parse", "--verify", "--quiet", f"{args.base}^{{commit}}").returncode != 0:
        print(f"ERROR: base ref {args.base!r} not found; fetch it first")
        return 2

    problems = []
    for name in FROZEN_FILES:
        if not (root / name).is_file():
            problems.append(f"missing: {name}")
    diff = _git(root, "diff", "--name-status", args.base, "--", *FROZEN_FILES)
    if diff.returncode != 0:
        print(f"ERROR: git diff failed: {diff.stderr.strip()}")
        return 2
    for line in diff.stdout.splitlines():
        status, _, name = line.partition("\t")
        problems.append(f"changed ({status}): {name}")

    if problems:
        print(f"FAIL: frozen Instagram files differ from {args.base}:")
        for problem in sorted(set(problems)):
            print(f"  {problem}")
        return 1
    print(f"OK: {len(FROZEN_FILES)} frozen Instagram files identical to {args.base}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
