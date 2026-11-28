#!/usr/bin/env python3
"""E-mail alert check for the unified platform (Phase 6D). Standard library only.

Checks (each one only when configured):
  * health URLs: HTTP 200 and no JSON field equal to "error" / status "not_ready"
  * backup age: newest entry (mtime) inside a backup directory
  * disk usage: percent used per path
  * optional commands (no shell): Redis ping, queue length

One run = one pass. Run it from cron or a systemd timer (see docs/staging/6D-alerts.md).
Sends ONE mail per run listing all failing checks, using SMTP settings from environment variables.
Repeat suppression: with ALERT_STATE_FILE set, the same set of failures is mailed again only after
ALERT_REPEAT_HOURS; a recovery mail is sent when everything is OK again.

Exit codes: 0 all checks ok, 1 at least one check failing, 2 configuration or mail-sending error.

Secrets: SMTP password is read from ALERT_SMTP_PASSWORD only, never printed or put in a mail.
Never put secrets in health URLs (they appear in the alert text); use public health paths.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import smtplib
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Callable, Optional

# Defaults the owner can change by environment variable or flag.
DEFAULT_BACKUP_MAX_AGE_HOURS = 26.0
DEFAULT_DISK_MAX_PERCENT = 85.0
DEFAULT_QUEUE_MAX = 500
DEFAULT_REPEAT_HOURS = 6.0
DEFAULT_HTTP_TIMEOUT = 10.0
DEFAULT_CMD_TIMEOUT = 20.0


@dataclass
class Result:
    name: str
    ok: bool
    detail: str


# ---------------------------------------------------------------- checks (pure; I/O injected)

def check_health(url: str, fetch: Callable[[str, float], tuple[int, str]],
                 timeout: float = DEFAULT_HTTP_TIMEOUT) -> Result:
    name = f"health {url}"
    try:
        status, body = fetch(url, timeout)
    except Exception as exc:  # network error, timeout, TLS error
        return Result(name, False, f"request failed: {type(exc).__name__}: {exc}")
    if status != 200:
        return Result(name, False, f"HTTP {status}")
    try:
        data = json.loads(body)
    except ValueError:
        return Result(name, True, "HTTP 200")
    if isinstance(data, dict):
        bad = [k for k, v in data.items() if v == "error" or (k == "status" and v == "not_ready")]
        if bad:
            return Result(name, False, "HTTP 200 but reports error in: " + ", ".join(sorted(bad)))
    return Result(name, True, "HTTP 200")


def newest_mtime(directory: Path) -> Optional[float]:
    """Newest mtime of the directory's direct entries (backup folders or files); None if empty/missing."""
    try:
        times = [p.stat().st_mtime for p in directory.iterdir()]
    except OSError:
        return None
    return max(times) if times else None


def check_backup_age(directory: str, max_age_hours: float, now: float,
                     mtime_fn: Callable[[Path], Optional[float]] = newest_mtime) -> Result:
    name = f"backup age {directory}"
    m = mtime_fn(Path(directory))
    if m is None:
        return Result(name, False, "directory missing, unreadable or empty")
    age_h = (now - m) / 3600.0
    if age_h > max_age_hours:
        return Result(name, False, f"newest backup is {age_h:.1f} h old (limit {max_age_hours:g} h)")
    return Result(name, True, f"newest backup is {age_h:.1f} h old (limit {max_age_hours:g} h)")


def check_disk(path: str, max_percent: float,
               usage_fn: Callable[[str], tuple[int, int]] = lambda p: shutil.disk_usage(p)[:2]) -> Result:
    name = f"disk {path}"
    try:
        total, used = usage_fn(path)
    except OSError as exc:
        return Result(name, False, f"cannot read usage: {exc}")
    pct = 100.0 * used / total if total else 100.0
    detail = f"{pct:.1f}% used (limit {max_percent:g}%)"
    return Result(name, pct <= max_percent, detail)


def check_command_expect(name: str, cmd: str, expect: str,
                         run: Callable[[list[str], float], tuple[int, str]]) -> Result:
    label = f"command {name}"
    try:
        code, out = run(shlex.split(cmd), DEFAULT_CMD_TIMEOUT)
    except Exception as exc:
        return Result(label, False, f"could not run: {type(exc).__name__}: {exc}")
    if code != 0:
        return Result(label, False, f"exit code {code}")
    if expect not in out:
        return Result(label, False, f"output did not contain {expect!r}")
    return Result(label, True, "ok")


def check_queue_length(name: str, cmd: str, max_len: int,
                       run: Callable[[list[str], float], tuple[int, str]]) -> Result:
    label = f"queue {name}"
    try:
        code, out = run(shlex.split(cmd), DEFAULT_CMD_TIMEOUT)
    except Exception as exc:
        return Result(label, False, f"could not run: {type(exc).__name__}: {exc}")
    if code != 0:
        return Result(label, False, f"exit code {code}")
    try:
        n = int(out.strip().split()[-1])
    except (ValueError, IndexError):
        return Result(label, False, "output is not a number")
    return Result(label, n <= max_len, f"length {n} (limit {max_len})")


# ---------------------------------------------------------------- real I/O

def http_fetch(url: str, timeout: float) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "business-mind-alert-check/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - owner-configured URL
            return resp.status, resp.read(65536).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""


def run_command(argv: list[str], timeout: float) -> tuple[int, str]:
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)  # noqa: S603
    return proc.returncode, proc.stdout


# ---------------------------------------------------------------- state and mail

def load_state(path: Optional[str]) -> dict:
    if not path:
        return {}
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def save_state(path: Optional[str], state: dict) -> None:
    if path:
        Path(path).write_text(json.dumps(state))


def decide(failing: list[Result], state: dict, now: float, repeat_hours: float) -> tuple[str, dict]:
    """Return (action, new_state). action: 'none' | 'alert' | 'recovery'."""
    key = sorted(r.name for r in failing)
    if not failing:
        if state.get("failing"):
            return "recovery", {"failing": [], "sent_at": now}
        return "none", {"failing": [], "sent_at": state.get("sent_at", 0)}
    same = state.get("failing") == key
    recent = (now - float(state.get("sent_at", 0))) < repeat_hours * 3600.0
    if same and recent:
        return "none", state
    return "alert", {"failing": key, "sent_at": now}


def build_message(subject: str, body: str, mail_from: str, mail_to: list[str]) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = ", ".join(mail_to)
    msg.set_content(body)
    return msg


def send_mail(msg: EmailMessage, env: dict, smtp_factory=smtplib.SMTP) -> None:
    host = env["ALERT_SMTP_HOST"]
    port = int(env.get("ALERT_SMTP_PORT", "587"))
    with smtp_factory(host, port, timeout=30) as smtp:
        if env.get("ALERT_SMTP_STARTTLS", "1") not in ("0", "false", "no"):
            smtp.starttls(context=ssl.create_default_context())
        user = env.get("ALERT_SMTP_USER")
        if user:
            smtp.login(user, env.get("ALERT_SMTP_PASSWORD", ""))
        smtp.send_message(msg)


def mail_settings_problem(env: dict) -> Optional[str]:
    missing = [k for k in ("ALERT_SMTP_HOST", "ALERT_MAIL_FROM", "ALERT_MAIL_TO") if not env.get(k)]
    return ("missing environment variables: " + ", ".join(missing)) if missing else None


# ---------------------------------------------------------------- orchestration

def split_list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def run_checks(env: dict, now: float, fetch=http_fetch, run=run_command,
               mtime_fn=newest_mtime, usage_fn=None) -> list[Result]:
    results: list[Result] = []
    for url in split_list(env.get("ALERT_HEALTH_URLS", "")):
        results.append(check_health(url, fetch))
    backup_dir = env.get("ALERT_BACKUP_DIR")
    if backup_dir:
        results.append(check_backup_age(
            backup_dir, float(env.get("ALERT_BACKUP_MAX_AGE_HOURS", DEFAULT_BACKUP_MAX_AGE_HOURS)),
            now, mtime_fn))
    disk_max = float(env.get("ALERT_DISK_MAX_PERCENT", DEFAULT_DISK_MAX_PERCENT))
    for path in split_list(env.get("ALERT_DISK_PATHS", "/")):
        if usage_fn is None:
            results.append(check_disk(path, disk_max))
        else:
            results.append(check_disk(path, disk_max, usage_fn))
    if env.get("ALERT_REDIS_CMD"):
        results.append(check_command_expect("redis ping", env["ALERT_REDIS_CMD"], "PONG", run))
    if env.get("ALERT_QUEUE_CMD"):
        results.append(check_queue_length(
            "backlog", env["ALERT_QUEUE_CMD"], int(env.get("ALERT_QUEUE_MAX", DEFAULT_QUEUE_MAX)), run))
    return results


def format_report(results: list[Result], host: str, now: float) -> str:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(now))
    lines = [f"Host: {host}", f"Time: {stamp}", ""]
    for r in results:
        lines.append(f"[{'OK  ' if r.ok else 'FAIL'}] {r.name}: {r.detail}")
    return "\n".join(lines) + "\n"


def main(argv: Optional[list[str]] = None, env: Optional[dict] = None, now: Optional[float] = None,
         fetch=http_fetch, run=run_command, mtime_fn=newest_mtime, usage_fn=None,
         smtp_factory=smtplib.SMTP, out=sys.stdout, err=sys.stderr, hostname: Optional[str] = None) -> int:
    env = dict(os.environ if env is None else env)
    now = time.time() if now is None else now
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="print what would be sent; send nothing; do not update state")
    ap.add_argument("--test-alert", action="store_true", help="send one deliberate TEST alert mail and exit")
    ap.add_argument("--health-url", action="append", default=[], help="extra health URL (repeatable)")
    args = ap.parse_args(argv)
    if args.health_url:
        env["ALERT_HEALTH_URLS"] = ",".join([env.get("ALERT_HEALTH_URLS", ""), *args.health_url])
    host = hostname or os.uname().nodename
    mail_from = env.get("ALERT_MAIL_FROM", "")
    mail_to = split_list(env.get("ALERT_MAIL_TO", ""))
    prefix = env.get("ALERT_SUBJECT_PREFIX", "[business-mind]")

    def deliver(subject: str, body: str) -> int:
        msg = build_message(subject, body, mail_from, mail_to)
        if args.dry_run:
            print("DRY RUN: would send this mail (nothing sent):", file=out)
            print(f"From: {mail_from or '(ALERT_MAIL_FROM not set)'}\nTo: {', '.join(mail_to) or '(ALERT_MAIL_TO not set)'}", file=out)
            print(f"Subject: {subject}\n\n{body}", file=out)
            return 0
        problem = mail_settings_problem(env)
        if problem:
            print(f"Cannot send mail: {problem}", file=err)
            return 2
        try:
            send_mail(msg, env, smtp_factory)
        except Exception as exc:  # report the type only; never echo settings
            print(f"Mail sending failed: {type(exc).__name__}", file=err)
            return 2
        print(f"Mail sent: {subject}", file=out)
        return 0

    if args.test_alert:
        body = (f"This is a deliberate TEST alert from {host}.\nIf you received it, e-mail alerting works.\n"
                f"Time: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(now))}\n")
        return deliver(f"{prefix} TEST alert from {host}", body)

    try:
        results = run_checks(env, now, fetch, run, mtime_fn, usage_fn)
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=err)
        return 2
    report = format_report(results, host, now)
    print(report, end="", file=out)
    failing = [r for r in results if not r.ok]

    state_path = env.get("ALERT_STATE_FILE")
    state = load_state(state_path)
    repeat = float(env.get("ALERT_REPEAT_HOURS", DEFAULT_REPEAT_HOURS))
    action, new_state = decide(failing, state, now, repeat)
    code = 1 if failing else 0
    if args.dry_run:
        action = "alert" if failing else "none"  # dry run ignores repeat suppression so you see the mail
    if action == "alert":
        rc = deliver(f"{prefix} ALERT on {host}: {len(failing)} check(s) failing", report)
    elif action == "recovery":
        rc = deliver(f"{prefix} RECOVERED on {host}: all checks ok", report)
    else:
        rc = 0
        if failing:
            print("Same failures already mailed recently; not mailing again.", file=out)
    if rc != 0:
        return rc
    if not args.dry_run:
        save_state(state_path, new_state)
    return code


if __name__ == "__main__":
    sys.exit(main())
