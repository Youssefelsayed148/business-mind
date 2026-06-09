#!/usr/bin/env python3
"""
Rehearsal lifecycle check.

Logs in as owner@osiris.com and exercises the full campaign lifecycle:
  list → activate paused → pause active → archive active → unarchive archived → fetch logs

Usage:
    python scripts/rehearsal_lifecycle_check.py
    python scripts/rehearsal_lifecycle_check.py --base-url http://localhost:8000
    python scripts/rehearsal_lifecycle_check.py --email owner@osiris.com --password password
"""

import argparse
import json
import sys
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_EMAIL    = "owner@osiris.com"
DEFAULT_PASSWORD = "password"


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

class APIClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token: str | None = None

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as err:
            raw = err.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {err.code} {method} {path}: {raw[:300]}") from err
        except urllib.error.URLError as err:
            raise RuntimeError(f"Connection error {method} {path}: {err}") from err

    def login(self, email: str, password: str) -> None:
        # OAuth2 password flow uses form-encoded body
        url = f"{self.base_url}/auth/login"
        form = f"username={urllib.parse.quote(email)}&password={urllib.parse.quote(password)}"
        data = form.encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                self.token = body["access_token"]
        except urllib.error.HTTPError as err:
            raw = err.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Login failed HTTP {err.code}: {raw[:300]}") from err

    def get(self, path: str) -> dict | list:
        return self._request("GET", path)

    def post(self, path: str, body: dict | None = None) -> dict:
        return self._request("POST", path, body)


# We need urllib.parse for login
import urllib.parse


# ---------------------------------------------------------------------------
# Lifecycle steps
# ---------------------------------------------------------------------------

REHEARSAL_TAG = "[Rehearsal]"


def step(label: str, ok: bool = True, detail: str = "") -> None:
    symbol = "✓" if ok else "✗"
    line = f"  {symbol}  {label}"
    if detail:
        line += f"  — {detail}"
    print(line)


def run_lifecycle(client: APIClient) -> int:
    errors = 0

    # 1. List campaigns
    print("\n── Campaign list ──────────────────────────────────")
    try:
        campaigns: list[dict] = client.get("/campaigns")
        rehearsal = [c for c in campaigns if REHEARSAL_TAG in c.get("name", "")]
        step(f"Listed campaigns: {len(campaigns)} total, {len(rehearsal)} rehearsal")
    except RuntimeError as e:
        step("List campaigns", ok=False, detail=str(e))
        print("  Cannot continue without campaigns. Aborting.")
        return 1

    if not rehearsal:
        step("No rehearsal campaigns found — run seed_rehearsal first.", ok=False)
        return 1

    paused   = [c for c in rehearsal if c.get("status") == "paused"]
    active   = [c for c in rehearsal if c.get("status") == "active"]
    archived = [c for c in rehearsal if c.get("status") == "archived"]
    step(f"Rehearsal statuses: active={len(active)}  paused={len(paused)}  archived={len(archived)}")

    # 2. Activate a paused campaign
    print("\n── Activate paused campaign ───────────────────────")
    if paused:
        target = paused[0]
        try:
            result = client.post(f"/campaigns/{target['id']}/activate")
            step(f"Activated '{target['name']}'", detail=f"status → {result.get('status')}")
        except RuntimeError as e:
            step(f"Activate '{target['name']}'", ok=False, detail=str(e))
            errors += 1
    else:
        step("No paused campaigns to activate — skipping")

    # 3. Pause an active campaign (pick one different from what we just activated)
    print("\n── Pause active campaign ──────────────────────────")
    pause_candidates = [c for c in active if not (paused and c["id"] == paused[0]["id"])]
    if pause_candidates:
        target = pause_candidates[0]
        try:
            result = client.post(f"/campaigns/{target['id']}/pause")
            step(f"Paused '{target['name']}'", detail=f"status → {result.get('status')}")
        except RuntimeError as e:
            step(f"Pause '{target['name']}'", ok=False, detail=str(e))
            errors += 1
    else:
        step("No active campaigns to pause — skipping")

    # 4. Archive an active campaign
    print("\n── Archive active campaign ────────────────────────")
    archive_candidates = [c for c in active if not (pause_candidates and c["id"] == pause_candidates[0]["id"])]
    if archive_candidates:
        target = archive_candidates[0]
        try:
            result = client.post(f"/campaigns/{target['id']}/archive")
            step(f"Archived '{target['name']}'", detail=f"status → {result.get('status')}")
            just_archived_id = target["id"]
        except RuntimeError as e:
            step(f"Archive '{target['name']}'", ok=False, detail=str(e))
            errors += 1
            just_archived_id = None
    else:
        step("No active campaigns to archive — skipping")
        just_archived_id = None

    # 5. Unarchive a campaign
    print("\n── Unarchive campaign ─────────────────────────────")
    unarchive_id = just_archived_id or (archived[0]["id"] if archived else None)
    unarchive_name = just_archived_id and archive_candidates[0]["name"] or (archived[0]["name"] if archived else None)
    if unarchive_id:
        try:
            result = client.post(f"/campaigns/{unarchive_id}/unarchive")
            step(f"Unarchived '{unarchive_name}'", detail=f"status → {result.get('status')}")
        except RuntimeError as e:
            step(f"Unarchive '{unarchive_name}'", ok=False, detail=str(e))
            errors += 1
    else:
        step("No archived campaigns to unarchive — skipping")

    # 6. Fetch dashboard/logs if endpoint exists
    print("\n── Audit / automation logs ────────────────────────")
    for path, label in [("/dashboard/logs", "Audit logs"), ("/dashboard/overview", "Dashboard overview")]:
        try:
            data = client.get(path)
            count = len(data) if isinstance(data, list) else "ok"
            step(f"{label} ({path})", detail=f"{count} records" if isinstance(count, int) else count)
        except RuntimeError as e:
            msg = str(e)
            if "404" in msg:
                step(f"{label} ({path})", detail="endpoint not found — skipping")
            else:
                step(f"{label} ({path})", ok=False, detail=msg)
                errors += 1

    return errors


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Rehearsal campaign lifecycle check")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API base URL")
    parser.add_argument("--email",    default=DEFAULT_EMAIL,    help="Login email")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="Login password")
    args = parser.parse_args()

    client = APIClient(args.base_url)

    print(f"Connecting to {args.base_url} as {args.email} …")
    try:
        client.login(args.email, args.password)
        print("  Login: OK\n")
    except RuntimeError as e:
        print(f"  Login FAILED: {e}", file=sys.stderr)
        return 1

    errors = run_lifecycle(client)

    print("\n" + ("=" * 52))
    if errors == 0:
        print("  Lifecycle check PASSED — all steps completed.")
    else:
        print(f"  Lifecycle check DONE with {errors} error(s).")
    print("=" * 52)
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
