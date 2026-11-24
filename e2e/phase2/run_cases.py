"""Six mock e2e cases: 3 channels x delegation ON/OFF. Fake data, mocked Meta."""

import hashlib
import hmac
import json
import os
import sys
import time
import uuid

import httpx
from sqlalchemy import create_engine, text

sys.path[:0] = ["/app", "/e2e"]
from ids import MANY_CHANNELS  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402

MANY = os.environ["MANY_API_URL"]
META = "https://graph.facebook.com"
saas_db = create_engine(
    os.environ["SAAS_DATABASE_URL"].replace("postgresql://", "postgresql+psycopg://")
)
many_db = SessionLocal()
APP_SECRET = os.environ["META_APP_SECRET"]
TIMEOUT = float(os.environ.get("CASE_TIMEOUT", "120"))
TABLES = {
    "instagram": ("instagram_accounts", "ig_user_id"),
    "whatsapp": ("whatsapp_accounts", "phone_number_id"),
    "messenger": ("facebook_pages", "page_id"),
}


def webhook_payload(platform: str, ref: str, sender: str, body_text: str) -> dict:
    now_s, now_ms = int(time.time()), int(time.time() * 1000)
    if platform == "whatsapp":
        message = {
            "from": sender,
            "id": "wamid." + uuid.uuid4().hex[:12],
            "timestamp": str(now_s),
            "text": {"body": body_text},
            "type": "text",
        }
        value = {
            "metadata": {"phone_number_id": ref},
            "contacts": [{"profile": {"name": "E2E User"}, "wa_id": sender}],
            "messages": [message],
        }
        return {
            "object": "whatsapp_business_account",
            "entry": [{"id": "waba-e2e", "changes": [{"field": "messages", "value": value}]}],
        }
    return {
        "object": "instagram" if platform == "instagram" else "page",
        "entry": [
            {
                "id": ref,
                "time": now_ms,
                "messaging": [
                    {
                        "sender": {"id": sender},
                        "recipient": {"id": ref},
                        "timestamp": now_ms,
                        "message": {"mid": "mid." + uuid.uuid4().hex[:12], "text": body_text},
                    }
                ],
            }
        ],
    }


def post_webhook(payload: dict) -> httpx.Response:
    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = "sha256=" + hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return httpx.post(
        MANY + "/webhooks/meta",
        content=body,
        timeout=15,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature},
    )


def meta_requests() -> list[dict]:
    return httpx.get(META + "/__requests", timeout=10).json()


def many_rows(sql: str, **params) -> list:
    many_db.rollback()
    return list(many_db.execute(text(sql), params).mappings())


def saas_rows(sql: str, **params) -> list:
    with saas_db.connect() as conn:
        return list(conn.execute(text(sql), params).mappings())


def channel_id(platform: str, ref: str) -> str:
    table, column = TABLES[platform]
    return str(many_rows(f"SELECT id FROM {table} WHERE {column} = :ref", ref=ref)[0]["id"])


def run_case(n: int, platform: str, on: bool) -> dict:
    ref = MANY_CHANNELS[(platform, on)]
    cid = channel_id(platform, ref)
    sender = "1631555" + str(1000 + n) if platform == "whatsapp" else "9000" + str(n) + "0011"
    saas_events_before = saas_rows("SELECT count(*) AS c FROM channel_events")[0]["c"]
    meta_before = len(meta_requests())
    response = post_webhook(webhook_payload(platform, ref, sender, f"hello from e2e case {n}"))
    record: dict = {
        "case": n,
        "platform": platform,
        "delegation": "ON" if on else "OFF",
        "channel_ref": ref,
        "webhook_http": response.status_code,
    }
    deadline = time.time() + (TIMEOUT if on else 25)
    forwarded: list = []
    outbound: list = []
    delivered = False
    while time.time() < deadline:
        time.sleep(2)
        forwarded = many_rows(
            "SELECT status, attempts, last_error FROM saas_forward_events "
            "WHERE channel_id = :c ORDER BY seq",
            c=cid,
        )
        if on:
            outbound = many_rows(
                "SELECT m.status AS status FROM saas_outbound_messages o "
                "JOIN messages m ON m.id = o.message_pk WHERE o.channel_id = :c",
                c=cid,
            )
            if (
                forwarded
                and outbound
                and len(meta_requests()) > meta_before
                and all(o["status"] == "sent" for o in outbound)
            ):
                delivered = True
                break
    record["many_forward_events"] = [dict(r) for r in forwarded]
    record["saas_channel_events_delta"] = (
        saas_rows("SELECT count(*) AS c FROM channel_events")[0]["c"] - saas_events_before
    )
    record["many_outbound_from_saas"] = [dict(r) for r in outbound]
    record["mock_meta_requests"] = [
        {"host": r["host"], "path": r["path"], "body": r["body"]}
        for r in meta_requests()[meta_before:]
    ]
    if on:
        record["passed"] = (
            delivered
            and response.status_code == 200
            and record["saas_channel_events_delta"] >= 1
            and all(f["status"] == "sent" for f in forwarded)
        )
    else:
        record["passed"] = (
            response.status_code == 200
            and not forwarded
            and record["saas_channel_events_delta"] == 0
            and not record["mock_meta_requests"]
        )
    return record


CASES = [
    ("instagram", True),
    ("whatsapp", True),
    ("messenger", True),
    ("instagram", False),
    ("whatsapp", False),
    ("messenger", False),
]
results = []
for index, (platform, on) in enumerate(CASES, start=1):
    outcome = run_case(index, platform, on)
    results.append(outcome)
    print(json.dumps(outcome, default=str), flush=True)
print("SUMMARY " + " ".join(f"case{r['case']}={'PASS' if r['passed'] else 'FAIL'}" for r in results))
sys.exit(0 if all(r["passed"] for r in results) else 1)
