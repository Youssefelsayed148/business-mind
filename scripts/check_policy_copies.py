#!/usr/bin/env python3
"""Fail if the two internal_channel_policy.py copies differ byte for byte."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COPIES = (
    ROOT / "backend/app/services/internal_channel_policy.py",
    ROOT / "modules/saas/apps/api/app/channels/internal_channel_policy.py",
)


def main() -> int:
    try:
        first, second = (path.read_bytes() for path in COPIES)
    except OSError as exc:
        print(f"FAIL: cannot read policy copy: {exc}")
        return 1
    if first != second:
        print("FAIL: internal_channel_policy.py copies differ:")
        for path in COPIES:
            print(f"  {path.relative_to(ROOT)}")
        return 1
    print("OK: internal_channel_policy.py copies are byte-identical")
    return 0


if __name__ == "__main__":
    sys.exit(main())
