#!/usr/bin/env python3
"""
Rehearsal webhook batch sender.

Examples:
    python scripts/send_rehearsal_webhooks.py --count 100
    python scripts/send_rehearsal_webhooks.py --count 300 --keyword prompt
    python scripts/send_rehearsal_webhooks.py --count 100 --mode mixed
    python scripts/send_rehearsal_webhooks.py --count 50 --url http://localhost:8000/webhooks/meta
    python scripts/send_rehearsal_webhooks.py --keyword discount --media-id media_rehearsal_001
"""

import argparse
import hashlib
import hmac
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_WEBHOOK_URL = "http://localhost:8000/webhooks/meta"
ENV_FILE = Path(".env")

# Demo Instagram account IDs matching the seed data
DEMO_ACCOUNT_IDS = [
    "178400000000001",
    "178400000000002",
    "178400000000003",
    "178400000000004",
    "178400000000005",
    "178400000000006",
    "178400000000007",
    "178400000000008",
    "178400000000009",
    "178400000000010",
]

DEMO_MEDIA_IDS = [
    "media_rehearsal_001",
    "media_rehearsal_002",
    "media_rehearsal_003",
    "media_rehearsal_004",
    "media_rehearsal_005",
]

NON_MATCHING_MEDIA_IDS = [
    "media_rehearsal_nomatch_001",
    "media_rehearsal_nomatch_002",
]

KEYWORDS_POOL = [
    "price", "demo", "offer", "guide", "prompt",
    "discount", "start", "info", "course", "book",
]

USERNAMES = [
    "lina_fashion", "mark_travels", "sara_fit", "joe_tech", "nina_eats",
    "alex_beauty", "tom_learns", "rania_finance", "hassan_health", "layla_lifestyle",
    "chris_demo", "diana_info", "sam_guide", "pat_course", "robin_book",
    "user_wave", "commenter_x", "instafan_99", "real_human_1", "test_commenter",
    "happy_buyer", "curious_user", "deal_seeker", "offer_hunter", "promo_fan",
    "learn_more_now", "get_started_x", "info_seeker", "quick_question", "daily_user",
]

COMMENT_TEXTS_TEMPLATE = [
    "Hey! can you tell me more about {keyword}?",
    "interested in {keyword}, can you DM me?",
    "{keyword} please!",
    "what's the {keyword}?",
    "I'd love to know about {keyword} here",
    "send me the {keyword} info",
    "do you have a {keyword}?",
    "{keyword}",
    "asking about {keyword} 🙏",
    "need info on {keyword} ASAP",
]


# ---------------------------------------------------------------------------
# Env reading
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Payload building
# ---------------------------------------------------------------------------

def _unique_comment_id(counter: int) -> str:
    return f"rehearsal_comment_{counter:08d}_{random.randint(10000, 99999)}"


def _unique_user_id(counter: int) -> str:
    return f"rehearsal_user_{counter:06d}"


def build_payload(
    counter: int,
    keyword: str,
    account_id: str,
    media_id: str,
    ig_user_id: str,
    ig_username: str,
) -> dict:
    template = random.choice(COMMENT_TEXTS_TEMPLATE)
    comment_text = template.format(keyword=keyword)
    return {
        "object": "instagram",
        "entry": [
            {
                "id": account_id,
                "changes": [
                    {
                        "field": "mentions",
                        "value": {
                            "item": "comment",
                            "media_id": media_id,
                            "comment_id": _unique_comment_id(counter),
                            "from": {
                                "id": ig_user_id,
                                "username": ig_username,
                            },
                            "message": comment_text,
                        },
                    }
                ],
            }
        ],
    }


def sign_payload(body: bytes, app_secret: str) -> str:
    digest = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

def send_one(url: str, payload: dict, app_secret: str) -> tuple[int, float]:
    """Returns (http_status_code, elapsed_seconds)."""
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    signature = sign_payload(body, app_secret)
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
        },
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
            return resp.status, time.monotonic() - t0
    except urllib.error.HTTPError as err:
        err.read()
        return err.code, time.monotonic() - t0
    except urllib.error.URLError as err:
        print(f"  [CONN ERROR] {err}", file=sys.stderr)
        return 0, time.monotonic() - t0


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def resolve_keywords(mode: str, keyword: str | None) -> list[str]:
    if keyword:
        return [keyword]
    if mode == "mixed":
        return KEYWORDS_POOL
    # default: cycle through all keywords
    return KEYWORDS_POOL


def run_batch(
    url: str,
    count: int,
    app_secret: str,
    mode: str,
    keyword: str | None,
    verbose: bool,
    duplicate_comment_id: str | None = None,
    repeat_same_event: int = 0,
    media_id_override: str | None = None,
) -> None:
    keywords = resolve_keywords(mode, keyword)
    success = failed = rate_limited = 0
    elapsed_times: list[float] = []

    # --- Duplicate test mode ---
    if duplicate_comment_id or repeat_same_event > 0:
        repeat_n = repeat_same_event if repeat_same_event > 0 else count
        fixed_comment_id = duplicate_comment_id or f"rehearsal_dup_{random.randint(100000, 999999)}"
        kw = keyword or "demo"
        account_id = DEMO_ACCOUNT_IDS[0]
        media_id = media_id_override or DEMO_MEDIA_IDS[0]
        ig_user_id = "rehearsal_user_dup_001"
        ig_username = "dup_test_user"

        print(f"\nDuplicate test: sending comment_id={fixed_comment_id!r} × {repeat_n} → {url}\n")

        # Override build_payload to use a fixed comment_id for duplicate testing.
        def _dup_payload(i: int) -> dict:
            template = random.choice(COMMENT_TEXTS_TEMPLATE)
            return {
                "object": "instagram",
                "entry": [
                    {
                        "id": account_id,
                        "changes": [
                            {
                                "field": "mentions",
                                "value": {
                                    "item": "comment",
                                    "media_id": media_id,
                                    "comment_id": fixed_comment_id,
                                    "from": {"id": ig_user_id, "username": ig_username},
                                    "message": template.format(keyword=kw),
                                },
                            }
                        ],
                    }
                ],
            }

        for i in range(1, repeat_n + 1):
            payload = _dup_payload(i)
            status_code, elapsed = send_one(url, payload, app_secret)
            elapsed_times.append(elapsed)
            if status_code == 200:
                success += 1
                indicator = "."
            elif status_code == 429:
                rate_limited += 1
                indicator = "R"
            elif status_code == 0:
                failed += 1
                indicator = "E"
            else:
                failed += 1
                indicator = f"[{status_code}]"
            if verbose:
                print(f"  {i:4d}/{repeat_n}  status={status_code}  {elapsed*1000:.0f}ms  (same comment_id)")
            else:
                print(indicator, end="", flush=True)
                if i % 80 == 0:
                    print()

        if not verbose:
            print()

        avg_ms = (sum(elapsed_times) / len(elapsed_times) * 1000) if elapsed_times else 0
        print("\n" + "=" * 56)
        print(f"  Duplicate test  comment_id: {fixed_comment_id}")
        print(f"  Total sent:          {repeat_n}")
        print(f"  Success (200):       {success}  (all should be 200)")
        print(f"  Failed (non-200):    {failed}")
        print(f"  Rate limited (429):  {rate_limited}")
        print(f"  Avg response time:   {avg_ms:.1f} ms")
        print(f"  Expected result:     only 1 lead/message created (first event processed)")
        print("=" * 56)
        return

    # --- Normal batch mode ---
    total = count
    print(f"\nSending {total} webhooks → {url}")
    print(f"Mode: {mode!r}  Keyword(s): {', '.join(keywords)}\n")

    for i in range(1, total + 1):
        kw = keywords[(i - 1) % len(keywords)]
        account_id = random.choice(DEMO_ACCOUNT_IDS)
        if media_id_override:
            media_id = media_id_override
        elif mode == "mixed" and i % 5 == 0:
            media_id = random.choice(NON_MATCHING_MEDIA_IDS)
        else:
            media_id = random.choice(DEMO_MEDIA_IDS)
        ig_user_id = _unique_user_id(i)
        ig_username = f"{random.choice(USERNAMES)}_{i}"

        payload = build_payload(i, kw, account_id, media_id, ig_user_id, ig_username)
        status_code, elapsed = send_one(url, payload, app_secret)
        elapsed_times.append(elapsed)

        if status_code == 200:
            success += 1
            indicator = "."
        elif status_code == 429:
            rate_limited += 1
            indicator = "R"
        elif status_code == 0:
            failed += 1
            indicator = "E"
        else:
            failed += 1
            indicator = f"[{status_code}]"

        if verbose:
            print(f"  {i:4d}/{total}  status={status_code}  kw={kw!r}  media_id={media_id!r}  {elapsed*1000:.0f}ms")
        else:
            print(indicator, end="", flush=True)
            if i % 80 == 0:
                print()

    if not verbose:
        print()

    avg_ms = (sum(elapsed_times) / len(elapsed_times) * 1000) if elapsed_times else 0

    print("\n" + "=" * 50)
    print(f"  Total sent:          {total}")
    print(f"  Success (200):       {success}")
    print(f"  Failed (non-200):    {failed}")
    print(f"  Rate limited (429):  {rate_limited}")
    print(f"  Avg response time:   {avg_ms:.1f} ms")
    print("=" * 50)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Send rehearsal Instagram webhook events in batch."
    )
    parser.add_argument("--url",     default=DEFAULT_WEBHOOK_URL, help="Webhook endpoint URL")
    parser.add_argument("--count",   type=int, default=100,        help="Number of webhook events to send")
    parser.add_argument("--keyword", default=None,                  help="Force a specific trigger keyword")
    parser.add_argument("--mode",    default="sequential",          choices=["sequential", "mixed"], help="Keyword selection mode")
    parser.add_argument("--verbose", action="store_true",           help="Print one line per request")
    parser.add_argument("--media-id", default=None,                  help="Force a specific webhook media_id")
    parser.add_argument(
        "--duplicate-comment-id",
        default=None,
        metavar="COMMENT_ID",
        help="Send the same comment_id N (--count) times to verify duplicate protection",
    )
    parser.add_argument(
        "--repeat-same-event",
        type=int,
        default=0,
        metavar="N",
        help="Send the same auto-generated comment_id N times (duplicate test shorthand)",
    )
    args = parser.parse_args()

    try:
        app_secret = read_env_value("META_APP_SECRET")
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    run_batch(
        url=args.url,
        count=args.count,
        app_secret=app_secret,
        mode=args.mode,
        keyword=args.keyword,
        verbose=args.verbose,
        duplicate_comment_id=args.duplicate_comment_id,
        repeat_same_event=args.repeat_same_event,
        media_id_override=args.media_id,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
