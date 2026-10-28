#!/usr/bin/env python3
"""Production configuration preflight.

Usage: python scripts/preflight_prod.py .env.production

Prints PASS/FAIL per check and never prints a value from the env file.
Exit code is 1 if any check fails. Standard library only.
"""
import base64
import binascii
import ipaddress
import sys
from pathlib import Path
from urllib.parse import urlparse

REQUIRED = [
    "APP_BASE_URL",
    "FRONTEND_URL",
    "ALLOWED_ORIGINS",
    "DATABASE_URL",
    "REDIS_URL",
    "JWT_SECRET",
    "APP_SECRET_KEY",
    "TOKEN_ENCRYPTION_KEY",
    "META_APP_ID",
    "META_APP_SECRET",
    "META_WEBHOOK_VERIFY_TOKEN",
]
# Defaults/placeholders that must not reach production (see app/core/config.py
# and .env.production.example).
DEFAULT_SECRETS = {"change_me_local_app_secret", "change_me", "changeme", "secret"}


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def is_set(value: str | None) -> bool:
    return bool(value) and not value.startswith("FILL")


def is_true(value: str | None) -> bool:
    return (value or "").strip().lower() == "true"


def is_false(value: str | None) -> bool:
    return (value or "").strip().lower() == "false"


def valid_fernet_key(value: str) -> bool:
    try:
        return len(base64.urlsafe_b64decode(value.encode("utf-8"))) == 32
    except (binascii.Error, ValueError):
        return False


def is_default_secret(value: str | None) -> bool:
    if not is_set(value):
        return True
    return value.lower() in DEFAULT_SECRETS or len(value) < 32


def https_origins(value: str | None) -> bool:
    origins = [item.strip() for item in (value or "").split(",") if item.strip()]
    return bool(origins) and all(urlparse(item).scheme == "https" for item in origins)


def specific_proxy_peers(value: str | None) -> bool:
    """Require explicit IP/CIDR peers; broad wildcard trust is never safe."""
    peers = [peer.strip() for peer in (value or "").split(",")]
    if not all(peers):
        return False
    try:
        return all(ipaddress.ip_network(peer, strict=False).prefixlen > 0 for peer in peers)
    except ValueError:
        return False


def run_checks(env: dict[str, str]) -> list[tuple[str, bool]]:
    missing = [name for name in REQUIRED if not is_set(env.get(name))]
    checks = [
        (f"required vars present ({len(missing)} missing: {', '.join(missing) or 'none'})", not missing),
        ("APP_ENV=production", env.get("APP_ENV", "").lower() == "production"),
        ("DISABLE_DOCS=true", is_true(env.get("DISABLE_DOCS"))),
        ("FORWARDED_ALLOW_IPS names explicit proxy IPs/CIDRs", specific_proxy_peers(env.get("FORWARDED_ALLOW_IPS"))),
        ("META_MOCK_PRIVATE_REPLIES=false", is_false(env.get("META_MOCK_PRIVATE_REPLIES"))),
        (
            "TOKEN_ENCRYPTION_KEY is a valid Fernet key",
            valid_fernet_key(env.get("TOKEN_ENCRYPTION_KEY", "")),
        ),
        ("JWT_SECRET is not a default/placeholder (>= 32 chars)", not is_default_secret(env.get("JWT_SECRET"))),
        (
            "APP_SECRET_KEY is not a default/placeholder (>= 32 chars)",
            not is_default_secret(env.get("APP_SECRET_KEY")),
        ),
        ("ALLOWED_ORIGINS are all https", https_origins(env.get("ALLOWED_ORIGINS"))),
    ]
    # AI is on by default in the app; it needs a key to work.
    if (env.get("AI_ENABLED_GLOBAL", "true")).strip().lower() != "false":
        checks.append(("OPENAI_API_KEY set while AI_ENABLED_GLOBAL is on", is_set(env.get("OPENAI_API_KEY"))))
    return checks


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python scripts/preflight_prod.py <env-file>")
        return 2
    path = Path(argv[1])
    if not path.is_file():
        print(f"FAIL env file not found: {path}")
        return 2
    results = run_checks(parse_env(path))
    for label, ok in results:
        print(f"{'PASS' if ok else 'FAIL'}  {label}")
    failed = sum(1 for _, ok in results if not ok)
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
