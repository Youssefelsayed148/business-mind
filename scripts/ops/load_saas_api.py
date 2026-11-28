#!/usr/bin/env python3
"""Read-only load check for the SaaS API (Phase 6F). Standard library only.

Sends GET requests only, with fixed concurrency for a fixed duration, and prints a table with
requests, errors, error rate, requests/s and p50/p95/p99 latency (total and per path).

Two mixes:
  * unauthenticated: health and public config paths (default /health, /ready, /api/v1/auth/config)
  * authenticated (optional): paths that need a session. The session cookie comes from the
    environment variable LOAD_SESSION_COOKIE (either "name=value" or just the value, which is sent as
    chatbot_session=<value>). It is never printed. Use a throwaway staging user.
    With --tenant-id the default authenticated mix is /api/v1/auth/me plus the tenant's contacts,
    inbox and inbox counts; otherwise only /api/v1/auth/me. Override with --auth-path (repeatable).

Safety:
  * Refuses any host that does not look like staging (loopback, or a host name label that is
    "staging"/"stg" or starts/ends with them) unless --i-know-this-is-staging is given.
  * Hard caps: concurrency <= 100, duration <= 300 s.
  * An authenticated preflight request must return 2xx, or the run aborts (no flood of 401s).

Example:
  LOAD_SESSION_COOKIE=... python3 scripts/ops/load_saas_api.py --base-url https://saas-api.staging.example.invalid \\
      --concurrency 10 --duration 60 --tenant-id TENANT_UUID
"""
from __future__ import annotations

import argparse
import http.client
import ipaddress
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlsplit

MAX_CONCURRENCY = 100
MAX_DURATION = 300.0
DEFAULT_UNAUTH_PATHS = ["/health", "/ready", "/api/v1/auth/config"]
DEFAULT_COOKIE_NAME = "chatbot_session"


# ---------------------------------------------------------------- statistics (unit tested)

def percentile(sorted_values: list[float], p: float) -> float:
    """Linear-interpolation percentile (p in 0..100) of an ascending list. Empty list -> nan."""
    if not sorted_values:
        return float("nan")
    if p <= 0:
        return sorted_values[0]
    if p >= 100:
        return sorted_values[-1]
    k = (len(sorted_values) - 1) * p / 100.0
    lo = int(k)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


@dataclass
class Summary:
    name: str
    requests: int
    errors: int
    error_rate: float  # percent
    rps: float
    p50: float
    p95: float
    p99: float


def summarize(name: str, latencies_ms: list[float], errors: int, elapsed_s: float) -> Summary:
    """latencies_ms: latencies of ALL requests (ok and failed that got a response or timed out)."""
    total = len(latencies_ms)
    s = sorted(latencies_ms)
    return Summary(
        name=name,
        requests=total,
        errors=errors,
        error_rate=(100.0 * errors / total) if total else 0.0,
        rps=(total / elapsed_s) if elapsed_s > 0 else 0.0,
        p50=percentile(s, 50), p95=percentile(s, 95), p99=percentile(s, 99),
    )


def _fmt(v: float) -> str:
    return "n/a" if v != v else f"{v:.1f}"


def format_table(rows: list[Summary]) -> str:
    head = f"{'path':<44} {'requests':>9} {'errors':>7} {'err %':>7} {'req/s':>8} {'p50 ms':>8} {'p95 ms':>8} {'p99 ms':>8}"
    lines = [head, "-" * len(head)]
    for r in rows:
        lines.append(f"{r.name[:44]:<44} {r.requests:>9} {r.errors:>7} {r.error_rate:>7.2f} {r.rps:>8.1f} "
                     f"{_fmt(r.p50):>8} {_fmt(r.p95):>8} {_fmt(r.p99):>8}")
    return "\n".join(lines)


# ---------------------------------------------------------------- safety helpers (unit tested)

def is_staging_host(host: str) -> bool:
    host = (host or "").lower().strip("[]")
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        pass
    for label in host.split("."):
        if label in ("staging", "stg") or label.startswith(("staging-", "stg-")) or label.endswith(("-staging", "-stg")):
            return True
    return False


def normalize_cookie(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    if "=" in raw:
        return raw
    return f"{DEFAULT_COOKIE_NAME}={raw}"


def build_auth_paths(tenant_id: Optional[str], explicit: list[str]) -> list[str]:
    if explicit:
        return explicit
    paths = ["/api/v1/auth/me"]
    if tenant_id:
        if not re.fullmatch(r"[A-Za-z0-9-]{1,64}", tenant_id):
            raise ValueError("--tenant-id has unexpected characters")
        base = f"/api/v1/tenants/{tenant_id}"
        paths += [f"{base}/contacts?limit=20", f"{base}/inbox", f"{base}/inbox/counts"]
    return paths


# ---------------------------------------------------------------- load generator

@dataclass
class Bucket:
    latencies: list = field(default_factory=list)
    errors: int = 0


def make_conn(scheme: str, host: str, port: Optional[int], timeout: float):
    cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
    return cls(host, port, timeout=timeout)


def one_get(conn, path: str, cookie: str) -> tuple[bool, float]:
    """GET only. Returns (ok, latency_ms). ok means a 2xx answer. Raises on connection errors."""
    headers = {"User-Agent": "business-mind-load-check/1", "Accept": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    t0 = time.perf_counter()
    conn.request("GET", path, headers=headers)
    resp = conn.getresponse()
    resp.read()
    ms = (time.perf_counter() - t0) * 1000.0
    return 200 <= resp.status < 300, ms


def worker(scheme, host, port, mix, deadline, timeout, buckets, lock, offset):
    conn = make_conn(scheme, host, port, timeout)
    i = offset
    while time.monotonic() < deadline:
        path, cookie = mix[i % len(mix)]
        i += 1
        t0 = time.perf_counter()
        try:
            ok, ms = one_get(conn, path, cookie)
            err = not ok
        except Exception:
            ms = (time.perf_counter() - t0) * 1000.0
            err = True
            try:
                conn.close()
            except Exception:
                pass
            conn = make_conn(scheme, host, port, timeout)
        with lock:
            b = buckets.setdefault(path, Bucket())
            b.latencies.append(ms)
            if err:
                b.errors += 1
    try:
        conn.close()
    except Exception:
        pass


def run_load(base_url: str, mix: list[tuple[str, str]], concurrency: int, duration: float, timeout: float):
    u = urlsplit(base_url)
    buckets: dict[str, Bucket] = {}
    lock = threading.Lock()
    t0 = time.monotonic()
    deadline = t0 + duration
    threads = [threading.Thread(target=worker, args=(u.scheme, u.hostname, u.port, mix, deadline, timeout, buckets, lock, n))
               for n in range(concurrency)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.monotonic() - t0
    rows = [summarize(p, b.latencies, b.errors, elapsed) for p, b in sorted(buckets.items())]
    all_lat = [x for b in buckets.values() for x in b.latencies]
    total = summarize("TOTAL", all_lat, sum(b.errors for b in buckets.values()), elapsed)
    return rows, total, elapsed


def main(argv: Optional[list[str]] = None, env: Optional[dict] = None, out=sys.stdout, err=sys.stderr) -> int:
    env = os.environ if env is None else env
    ap = argparse.ArgumentParser(description="Read-only GET load check for the SaaS API (staging only).")
    ap.add_argument("--base-url", required=True, help="for example https://saas-api.staging.example.invalid")
    ap.add_argument("--concurrency", type=int, default=5)
    ap.add_argument("--duration", type=float, default=30.0, help="seconds")
    ap.add_argument("--timeout", type=float, default=10.0, help="per request, seconds")
    ap.add_argument("--path", action="append", default=[], help="unauthenticated GET path (repeatable); default health set")
    ap.add_argument("--auth-path", action="append", default=[], help="authenticated GET path (repeatable)")
    ap.add_argument("--tenant-id", default=None, help="adds tenant read paths to the authenticated mix")
    ap.add_argument("--auth", action="store_true", help="include the authenticated mix (needs LOAD_SESSION_COOKIE)")
    ap.add_argument("--i-know-this-is-staging", action="store_true", help="allow a host that does not look like staging")
    args = ap.parse_args(argv)

    u = urlsplit(args.base_url)
    if u.scheme not in ("http", "https") or not u.hostname:
        print("Error: --base-url must be http(s)://host[:port]", file=err)
        return 2
    if not is_staging_host(u.hostname) and not args.i_know_this_is_staging:
        print(f"Refusing: host '{u.hostname}' does not look like staging. "
              "Use a staging host, or pass --i-know-this-is-staging if you are sure.", file=err)
        return 2
    if not (1 <= args.concurrency <= MAX_CONCURRENCY) or not (1 <= args.duration <= MAX_DURATION):
        print(f"Error: concurrency must be 1..{MAX_CONCURRENCY} and duration 1..{MAX_DURATION:g} seconds", file=err)
        return 2
    for p in [*args.path, *args.auth_path]:
        if not p.startswith("/"):
            print("Error: paths must start with /", file=err)
            return 2

    mix: list[tuple[str, str]] = [(p, "") for p in (args.path or DEFAULT_UNAUTH_PATHS)]
    if args.auth:
        cookie = normalize_cookie(env.get("LOAD_SESSION_COOKIE", ""))
        if not cookie:
            print("Error: --auth needs the LOAD_SESSION_COOKIE environment variable", file=err)
            return 2
        try:
            auth_paths = build_auth_paths(args.tenant_id, args.auth_path)
        except ValueError as exc:
            print(f"Error: {exc}", file=err)
            return 2
        # Preflight: one request on the first authenticated path must succeed.
        conn = make_conn(u.scheme, u.hostname, u.port, args.timeout)
        try:
            ok, _ = one_get(conn, auth_paths[0], cookie)
        except Exception as exc:
            print(f"Preflight failed: {type(exc).__name__}", file=err)
            return 2
        finally:
            conn.close()
        if not ok:
            print(f"Preflight failed: {auth_paths[0]} did not return 2xx. Check the session cookie and tenant id. Aborting.", file=err)
            return 2
        mix += [(p, cookie) for p in auth_paths]

    print(f"Target: {u.scheme}://{u.hostname}{':' + str(u.port) if u.port else ''}  concurrency={args.concurrency} "
          f"duration={args.duration:g}s  paths={len(mix)}  authenticated={'yes' if args.auth else 'no'}  method=GET only", file=out)
    rows, total, elapsed = run_load(args.base_url, mix, args.concurrency, args.duration, args.timeout)
    print(format_table([*rows, total]), file=out)
    print(f"elapsed {elapsed:.1f}s", file=out)
    return 1 if total.requests == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
