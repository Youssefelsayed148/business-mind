"""A fake SaaS for contract tests (M-07).

Stands in for POST {saas}/api/channels/manyosiris/events. It verifies the
contract independently of Many's own signing module (plain hmac/hashlib),
records every request, dedupes on (connection_id, event_id) like the real
SaaS, and answers from a configurable script. It also signs calls *into*
Many (`sign`), again without importing Many's signing code.
"""

import hashlib
import hmac
import json
import time
from collections import deque
from dataclasses import dataclass, field

import httpx

EVENTS_PATH = "/api/channels/manyosiris/events"


@dataclass
class Recorded:
    path: str
    headers: dict
    body: bytes
    payload: dict | None
    signature_ok: bool
    problems: list = field(default_factory=list)
    status: int | None = None  # None: connection dropped before any response


class FakeSaas:
    def __init__(self, connection_id: str, secrets: list[str], max_skew: int = 300):
        self.connection_id = connection_id
        self.secrets = list(secrets)
        self.max_skew = max_skew
        self.requests: list[Recorded] = []
        self.script: deque = deque()  # httpx.Response | Exception | callable(request)
        self.seen: set[str] = set()
        self.down = False

    # --- configuration -----------------------------------------------------
    def respond(self, *responses):
        self.script.extend(responses)

    # --- server ------------------------------------------------------------
    def handle(self, request: httpx.Request) -> httpx.Response:
        body = request.content
        problems = []
        ts = request.headers.get("X-Osiris-Timestamp", "")
        sig = request.headers.get("X-Osiris-Signature", "")
        conn = request.headers.get("X-Osiris-Connection", "")
        signature_ok = False
        try:
            fresh = abs(time.time() - int(ts)) <= self.max_skew
        except ValueError:
            fresh = False
        if not fresh:
            problems.append("stale_or_missing_timestamp")
        if conn != self.connection_id:
            problems.append("wrong_connection")
        if not sig.startswith("sha256="):
            problems.append("bad_signature_format")
        else:
            for secret in self.secrets:
                expected = hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
                if hmac.compare_digest(expected.encode(), sig[len("sha256="):].encode()):
                    signature_ok = True
        if not signature_ok:
            problems.append("bad_signature")
        if len(body) > 64 * 1024:
            problems.append("body_too_large")
        if request.headers.get("Content-Type", "").split(";")[0] != "application/json":
            problems.append("content_type")
        payload = None
        try:
            payload = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            problems.append("not_json")
        if isinstance(payload, dict):
            problems += self._envelope_problems(payload)
        rec = Recorded(request.url.path, dict(request.headers), body, payload, signature_ok, problems)
        self.requests.append(rec)

        if self.down:
            raise httpx.ConnectError("fake saas is down", request=request)
        response = self._respond(request, payload, signature_ok and fresh and conn == self.connection_id)
        rec.status = response.status_code
        return response

    def _respond(self, request, payload, authentic: bool) -> httpx.Response:
        if not authentic:
            return httpx.Response(401, json={"detail": "unauthorized"})
        if self.script:
            step = self.script.popleft()
            if isinstance(step, Exception):
                raise step
            if callable(step):
                return step(request)
            return step
        if isinstance(payload, dict):
            key = (payload.get("connection_id"), payload.get("event_id"))
            if key in self.seen:
                return httpx.Response(202, json={"status": "duplicate"})
            self.seen.add(key)
        return httpx.Response(202, json={"status": "accepted"})

    @staticmethod
    def _envelope_problems(p: dict) -> list:
        out = []
        if p.get("version") != 1:
            out.append("version")
        if not isinstance(p.get("event_id"), str) or not 0 < len(p["event_id"]) <= 128:
            out.append("event_id")
        if p.get("event_type") not in {"message.received", "message.status", "channel.status"}:
            out.append("event_type")
        if not isinstance(p.get("connection_id"), str):
            out.append("connection_id")
        if not str(p.get("occurred_at", "")).endswith("Z"):
            out.append("occurred_at")
        return out

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handle))

    # --- inspection --------------------------------------------------------
    @property
    def problems(self) -> list:
        return [(r.payload and r.payload.get("event_id"), r.problems) for r in self.requests if r.problems]

    def delivered(self, event_type: str | None = None) -> list[dict]:
        """Payloads the fake accepted, once per event_id, in arrival order."""
        seen, out = set(), []
        for r in self.requests:
            p = r.payload
            if not r.signature_ok or not (r.status and 200 <= r.status < 300) or not isinstance(p, dict) or p["event_id"] in seen:
                continue
            if event_type is None or p["event_type"] == event_type:
                seen.add(p["event_id"])
                out.append(p)
        return out

    def attempts_for(self, event_id: str) -> int:
        return sum(1 for r in self.requests if r.payload and r.payload.get("event_id") == event_id)


def sign(connection_id: str, secret: str, body: bytes = b"", *, now: float | None = None) -> dict:
    """Headers for a SaaS -> Many call, built from the contract text only."""
    ts = str(int(now if now is not None else time.time()))
    digest = hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    return {"X-Osiris-Connection": connection_id, "X-Osiris-Timestamp": ts,
            "X-Osiris-Signature": f"sha256={digest}", "Content-Type": "application/json"}
