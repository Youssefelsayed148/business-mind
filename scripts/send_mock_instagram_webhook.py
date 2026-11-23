#!/usr/bin/env python3
import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_WEBHOOK_URL = "http://localhost:8000/webhooks/meta"
ENV_FILE = Path(".env")


def read_env_value(key: str, env_file: Path = ENV_FILE) -> str:
    if key in os.environ:
        return os.environ[key]

    if not env_file.exists():
        raise RuntimeError(f"Missing env file: {env_file}")

    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        name, value = stripped.split("=", 1)
        if name.strip() == key:
            value = value.strip()
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]
            return value

    raise RuntimeError(f"{key} is not set in {env_file}")


def build_payload() -> dict:
    return {
        "object": "instagram",
        "entry": [
            {
                "id": "178400000000001",
                "changes": [
                    {
                        "field": "mentions",
                        "value": {
                            "item": "comment",
                            "media_id": "179900000000001",
                            "comment_id": "comment_002",
                            "from": {
                                "id": "user_001",
                                "username": "ahmed_test",
                            },
                            "message": "prompt",
                        },
                    }
                ],
            }
        ],
    }


def main() -> int:
    app_secret = read_env_value("META_APP_SECRET")
    webhook_url = os.environ.get("WEBHOOK_URL", DEFAULT_WEBHOOK_URL)

    body = json.dumps(build_payload(), separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    digest = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    signature = f"sha256={digest}"

    request = urllib.request.Request(
        webhook_url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
        },
    )

    print(f"POST {webhook_url}")
    print(f"X-Hub-Signature-256: {signature}")
    print(body.decode("utf-8"))

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            print(f"Status: {response.status}")
            print(f"Body: {response_body}")
            return 0
    except urllib.error.HTTPError as error:
        response_body = error.read().decode("utf-8", errors="replace")
        print(f"Status: {error.code}")
        print(f"Body: {response_body}")
        return 1
    except urllib.error.URLError as error:
        print(f"Request failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
