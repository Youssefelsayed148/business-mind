#!/usr/bin/env python3
"""Offline migration of existing Many users into the SaaS identity (design 7).

Subcommands (dry-run is the default and never writes):
  report   inventory both databases, classify every user, print a summary and write the
           full report (emails, classes, hash algorithm of every Many row) to --out.
  apply    write the links. Needs the hash of a report the owner reviewed
           (--report-hash), the typed database names (--confirm-databases) and --yes.
  verify   read-only post-checks.
  map-report / map-apply / verify-mapping
           organization to workspace mapping (Phase 4A, design 4.1). The owner supplies a JSON
           file of {"tenant_id": ..., "workspace_id": ...} pairs. map-report is read-only and
           classifies every pair; map-apply needs its report hash, the typed database names and
           --yes, refuses on any conflict, and sets both sides (tenants.many_workspace_id and
           workspaces.saas_tenant_id). verify-mapping checks that both sides agree.

Connections come from the environment only and are never printed (only host and
database name are):
  MANY_DATABASE_URL   Many Postgres      SAAS_DATABASE_URL   SaaS Postgres

Rules that hold on every run:
- A password hash is never printed, logged or put in the report: the report carries the
  algorithm and its cost parameters only.
- Only an argon2id hash with sane parameters is carried to the SaaS. Anything else
  (argon2i/d, bcrypt, PBKDF2, malformed, empty) is reported as "needs set-password
  link" and the old hash is NOT carried; that person gets an unusable password until
  they use a set-password link.
- Users present in both apps keep the SaaS password; the Many hash is replaced by an
  unusable one. Nothing is merged automatically: Many duplicates (case variants) and
  role conflicts are reported and skipped. No account becomes platform staff here.
- Linking is by the normalized email, offline, from a reviewed report only. The
  running apps never link by email.
- Both databases are locked with a Postgres advisory lock for the whole run, and apply
  is idempotent (a re-run changes nothing; a half-finished run completes).
- Not applied by `apply`: organization memberships. The organization to workspace mapping is
  a separate subcommand (map-apply) that only writes what the owner's mapping file lists.

Take a backup before apply. Never run this against production in Phase 3.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import sys
import unicodedata
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOCK_KEY = 0x1D3E_7117_0001  # advisory lock id: "identity migrate"
REPO_ROOT = Path(__file__).resolve().parent.parent
SUPPORTED_ARGON2 = {"min_m": 8192, "max_m": 1_048_576, "min_t": 1, "max_t": 10, "min_p": 1, "max_p": 16}
PHC_ARGON2 = re.compile(
    r"^\$(argon2id|argon2i|argon2d)\$v=(\d+)\$m=(\d+),t=(\d+),p=(\d+)\$([A-Za-z0-9+/]+)\$([A-Za-z0-9+/]+)$"
)
NOTES = [
    "Organization memberships are NOT applied by this tool; the organization to workspace mapping is a separate subcommand (map-apply).",
    "No account is made platform staff here; a Many global admin is flagged for an owner decision.",
    "Case-variant duplicates and role conflicts are skipped until the owner decides.",
]


# --- pure helpers (tested without a database) ----------------------------------------------------


def normalize_email(email: str) -> str:
    """Trim, NFKC, lower-case, IDNA-encode the domain. Dots and +tags are kept (design 3.2)."""
    text = unicodedata.normalize("NFKC", email.strip()).lower()
    local, sep, domain = text.rpartition("@")
    if not sep:
        return text
    try:
        domain = domain.encode("idna").decode("ascii")
    except UnicodeError:
        pass
    return f"{local}@{domain}"


def hash_info(password_hash: str | None) -> dict[str, Any]:
    """Algorithm and cost parameters of a stored hash; never the hash itself."""
    value = (password_hash or "").strip()
    if not value:
        return {"algorithm": "empty", "params": None, "carriable": False}
    match = PHC_ARGON2.match(value)
    if match:
        kind, version, m, t, p, salt, digest = match.groups()
        params = f"v={version},m={m},t={t},p={p}"
        limits = SUPPORTED_ARGON2
        ok = (
            kind == "argon2id"
            and version == "19"
            and limits["min_m"] <= int(m) <= limits["max_m"]
            and limits["min_t"] <= int(t) <= limits["max_t"]
            and limits["min_p"] <= int(p) <= limits["max_p"]
            and _b64_ok(salt, 8)
            and _b64_ok(digest, 16)
        )
        return {"algorithm": kind, "params": params, "carriable": ok}
    if value.startswith("$argon2"):
        return {"algorithm": "argon2-malformed", "params": None, "carriable": False}
    if value.startswith(("$2a$", "$2b$", "$2y$", "$2x$")):
        return {"algorithm": "bcrypt", "params": value[1:7].strip("$"), "carriable": False}
    if value.startswith("$pbkdf2"):
        return {"algorithm": value.split("$")[1], "params": None, "carriable": False}
    if value.startswith(("$scrypt$", "scrypt:")):
        return {"algorithm": "scrypt", "params": None, "carriable": False}
    return {"algorithm": "unknown", "params": None, "carriable": False}


def _b64_ok(text: str, minimum_bytes: int) -> bool:
    try:
        raw = base64.b64decode(text + "=" * (-len(text) % 4), validate=True)
    except ValueError:
        return False
    return len(raw) >= minimum_bytes


def unusable_hash() -> str:
    """A well-formed Argon2id hash of a random secret nobody sees."""
    try:
        from argon2 import PasswordHasher
    except ImportError as exc:  # pragma: no cover - both app venvs ship argon2-cffi
        raise SystemExit("argon2-cffi is required to apply the migration") from exc
    return PasswordHasher().hash(secrets.token_urlsafe(32))


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def report_hash(body: dict[str, Any]) -> str:
    """Stable hash of the report content (everything but the timestamp)."""
    return hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()


# --- inventory ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class ManyUser:
    id: str
    norm: str
    active: bool
    role: str
    hash: dict[str, Any]
    password_hash: str = ""
    sso_subject: str | None = None
    auth_source: str = "local"
    workspace_roles: tuple[str, ...] = ()


@dataclass(frozen=True)
class SaasUser:
    id: str
    norm: str
    active: bool
    staff: bool
    legacy_many_user_id: str | None
    membership_roles: tuple[str, ...] = ()


def inventory_many(conn: Any) -> list[ManyUser]:
    roles: dict[str, list[str]] = defaultdict(list)
    with conn.cursor() as cur:
        cur.execute("SELECT user_id, role FROM user_workspace_memberships")
        for user_id, role in cur.fetchall():
            roles[str(user_id)].append(str(role))
        cur.execute(
            "SELECT id, email, is_active, role, password_hash, sso_subject, auth_source FROM users"
        )
        rows = cur.fetchall()
    return [
        ManyUser(
            id=str(r[0]),
            norm=normalize_email(str(r[1])),
            active=bool(r[2]),
            role=str(r[3]),
            hash=hash_info(r[4]),
            password_hash=str(r[4] or ""),
            sso_subject=str(r[5]) if r[5] else None,
            auth_source=str(r[6]),
            workspace_roles=tuple(sorted(roles[str(r[0])])),
        )
        for r in rows
    ]


def inventory_saas(conn: Any) -> list[SaasUser]:
    roles: dict[str, list[str]] = defaultdict(list)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT user_id, COALESCE(org_role, role) FROM memberships WHERE status = 'active'"
        )
        for user_id, role in cur.fetchall():
            roles[str(user_id)].append(str(role))
        cur.execute(
            "SELECT id, email, is_active, is_platform_staff, legacy_many_user_id FROM users"
        )
        rows = cur.fetchall()
    return [
        SaasUser(
            id=str(r[0]),
            norm=normalize_email(str(r[1])),
            active=bool(r[2]),
            staff=bool(r[3]),
            legacy_many_user_id=str(r[4]) if r[4] else None,
            membership_roles=tuple(sorted(roles[str(r[0])])),
        )
        for r in rows
    ]


# --- classification -----------------------------------------------------------------------------


def build_report(many: list[ManyUser], saas: list[SaasUser]) -> dict[str, Any]:
    many_by: dict[str, list[ManyUser]] = defaultdict(list)
    saas_by: dict[str, list[SaasUser]] = defaultdict(list)
    for user in many:
        many_by[user.norm].append(user)
    for su in saas:
        saas_by[su.norm].append(su)
    many_ids = {m.id for m in many}
    rows: list[dict[str, Any]] = []
    for norm in sorted(set(many_by) | set(saas_by)):
        ms, ss = many_by.get(norm, []), saas_by.get(norm, [])
        row: dict[str, Any] = {"email": norm, "many_ids": sorted(m.id for m in ms)}
        row["saas_ids"] = sorted(s.id for s in ss)
        row["many_hashes"] = [
            {"many_id": m.id, "algorithm": m.hash["algorithm"], "params": m.hash["params"]}
            for m in sorted(ms, key=lambda m: m.id)
        ]
        flags: list[str] = []
        if len(ms) > 1:
            cls, action = "many_duplicates", "skip"
        elif len(ss) > 1:
            cls, action = "saas_duplicates", "skip"
        elif ms and not ss:
            cls = "many_only"
            m = ms[0]
            if m.sso_subject and m.auth_source == "sso":
                cls, action = "many_shadow_unlinked", "skip"  # shadow of a SaaS user not found
            elif m.hash["carriable"]:
                action = "create_saas_user_carry_hash"
            else:
                action, flags = "create_saas_user_needs_set_password_link", ["needs set-password link"]
        elif ss and not ms:
            legacy = ss[0].legacy_many_user_id
            if legacy and legacy not in many_ids:
                cls, action = "legacy_id_without_many_row", "skip"
            else:
                cls, action = "saas_only", "none"
        else:
            m, s = ms[0], ss[0]
            linked = m.sso_subject == s.id and s.legacy_many_user_id == m.id
            half = (m.sso_subject == s.id) != (s.legacy_many_user_id == m.id)
            if linked:
                cls, action = "both_linked", "none"
            elif half:
                cls, action = "both_half_linked", "complete_link"
            elif m.sso_subject or s.legacy_many_user_id:
                cls, action = "both_conflicting_links", "skip"
            else:
                cls, action = "both", "link_keep_saas_password"
            if m.active != s.active:
                flags.append("inactive on one side")
            if m.role == "admin" and not s.staff:
                flags.append("Many global admin is not SaaS staff: owner decision")
            if m.role != "admin" and s.staff:
                flags.append("SaaS staff has a non-admin Many role: owner decision")
            if cls == "both" and flags:
                cls, action = "both_with_conflicts", "skip"
        row.update(
            {
                "class": cls,
                "action": action,
                "flags": flags,
                "many_active": [m.active for m in ms],
                "many_roles": [m.role for m in ms],
                "many_workspace_roles": [list(m.workspace_roles) for m in ms],
                "saas_active": [s.active for s in ss],
                "saas_staff": [s.staff for s in ss],
                "saas_membership_roles": [list(s.membership_roles) for s in ss],
            }
        )
        rows.append(row)
    algorithms = Counter(u.hash["algorithm"] for u in many)
    body = {
        "users": rows,
        "summary": {
            "many_users": len(many),
            "saas_users": len(saas),
            "classes": dict(sorted(Counter(r["class"] for r in rows).items())),
            "actions": dict(sorted(Counter(r["action"] for r in rows).items())),
            "many_hash_algorithms": dict(sorted(algorithms.items())),
            "needs_set_password_link": sum(
                1 for r in rows if "needs set-password link" in r["flags"]
            ),
        },
        "notes": NOTES,
    }
    return {"report_hash": report_hash(body), **body}


# --- apply / verify -----------------------------------------------------------------------------


class Refused(Exception):
    pass


def db_name(conn: Any) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT current_database()")
        return str(cur.fetchone()[0])


def try_lock(conn: Any) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,))
        return bool(cur.fetchone()[0])


def unlock(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))


def apply_report(
    many_conn: Any,
    saas_conn: Any,
    *,
    expected_hash: str,
    confirm_databases: str,
) -> dict[str, int]:
    """Re-read both databases, refuse unless they still match the reviewed report, then link."""
    names = f"{db_name(many_conn)},{db_name(saas_conn)}"
    if confirm_databases != names:
        raise Refused(f"--confirm-databases must be exactly {names!r}")
    for label, conn in (("Many", many_conn), ("SaaS", saas_conn)):
        if not try_lock(conn):
            raise Refused(f"another migration holds the {label} advisory lock")
    try:
        many = inventory_many(many_conn)
        saas = inventory_saas(saas_conn)
        report = build_report(many, saas)
        if report["report_hash"] != expected_hash:
            raise Refused("the databases no longer match the reviewed report (hash differs)")
        many_by = {m.norm: m for m in many}
        saas_by = {s.norm: s for s in saas}
        counts: Counter[str] = Counter()
        for row in report["users"]:
            action = row["action"]
            if action in ("none", "skip"):
                counts["skipped" if action == "skip" else "unchanged"] += 1
                continue
            m = many_by[row["email"]]
            if action in ("create_saas_user_carry_hash", "create_saas_user_needs_set_password_link"):
                carried = action == "create_saas_user_carry_hash"
                new_id = str(uuid.uuid4())
                with saas_conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO users (id, email, password_hash, is_active, is_platform_staff,"
                        " legacy_many_user_id) VALUES (%s, %s, %s, %s, false, %s)",
                        (new_id, row["email"], m.password_hash if carried else unusable_hash(), m.active, m.id),
                    )
                saas_conn.commit()
                _link_many(many_conn, m.id, new_id)
                counts["created_carried" if carried else "created_needs_link"] += 1
            elif action == "link_keep_saas_password":
                s = saas_by[row["email"]]
                with saas_conn.cursor() as cur:
                    cur.execute("UPDATE users SET legacy_many_user_id = %s WHERE id = %s", (m.id, s.id))
                saas_conn.commit()
                _link_many(many_conn, m.id, s.id)
                counts["linked"] += 1
            elif action == "complete_link":
                s = saas_by[row["email"]]
                if s.legacy_many_user_id != m.id:
                    with saas_conn.cursor() as cur:
                        cur.execute(
                            "UPDATE users SET legacy_many_user_id = %s WHERE id = %s", (m.id, s.id)
                        )
                    saas_conn.commit()
                if m.sso_subject != s.id:
                    _link_many(many_conn, m.id, s.id)
                counts["completed"] += 1
        return dict(counts)
    finally:
        unlock(many_conn)
        unlock(saas_conn)


def _link_many(conn: Any, many_id: str, saas_id: str) -> None:
    """Mark the Many row as the shadow of a SaaS user; its own hash is replaced by an unusable one."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET sso_subject = %s, auth_source = 'sso', password_hash = %s WHERE id = %s",
            (saas_id, unusable_hash(), many_id),
        )
    conn.commit()


def verify(many_conn: Any, saas_conn: Any) -> dict[str, Any]:
    many, saas = inventory_many(many_conn), inventory_saas(saas_conn)
    saas_ids = {s.id: s for s in saas}
    problems: list[str] = []
    linked = 0
    for m in many:
        if m.sso_subject is None:
            continue
        s = saas_ids.get(m.sso_subject)
        if s is None:
            problems.append(f"Many user {m.id} points at a missing SaaS user")
        elif s.legacy_many_user_id != m.id:
            problems.append(f"Many user {m.id} and SaaS user {s.id} do not point at each other")
        else:
            linked += 1
        if m.auth_source != "sso":
            problems.append(f"Many user {m.id} is linked but auth_source is {m.auth_source}")
        if m.hash["algorithm"] != "argon2id":
            problems.append(f"Many user {m.id} kept a non-argon2id hash after linking")
    many_ids = {m.id for m in many}
    for s in saas:
        if s.legacy_many_user_id and s.legacy_many_user_id not in many_ids:
            problems.append(f"SaaS user {s.id} points at a missing Many user")
    unlinked = [m.id for m in many if m.sso_subject is None]
    return {
        "ok": not problems,
        "linked": linked,
        "many_users_not_linked": len(unlinked),
        "problems": problems,
    }


# --- organization to workspace mapping (Phase 4A, design 4.1) -----------------------------------


def _uuid_text(value: Any) -> str | None:
    return None if value is None else str(value)


def load_mapping(path: Path) -> list[tuple[str, str]]:
    """Read the owner's mapping file. Refuses anything that is not a clean 1:1 list of pairs."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Refused(f"cannot read the mapping file: {exc}") from exc
    if not isinstance(data, list) or not data:
        raise Refused("the mapping file must be a non-empty JSON list")
    pairs: list[tuple[str, str]] = []
    for item in data:
        if not isinstance(item, dict) or set(item) != {"tenant_id", "workspace_id"}:
            raise Refused('every entry must be exactly {"tenant_id": ..., "workspace_id": ...}')
        try:
            pairs.append((str(uuid.UUID(str(item["tenant_id"]))), str(uuid.UUID(str(item["workspace_id"])))))
        except ValueError as exc:
            raise Refused("tenant_id and workspace_id must be UUIDs") from exc
    if len({t for t, _ in pairs}) != len(pairs) or len({w for _, w in pairs}) != len(pairs):
        raise Refused("each organization and each workspace may appear only once (1:1 mapping)")
    return pairs


def _classify_pair(tenant: tuple[Any, ...] | None, workspace: tuple[Any, ...] | None,
                   tenant_id: str, workspace_id: str) -> str:
    if tenant is None:
        return "conflict_tenant_missing"
    if workspace is None:
        return "conflict_workspace_missing"
    t_status, t_ws = tenant[0], _uuid_text(tenant[1])
    w_tenant = _uuid_text(workspace[0])
    if t_ws == workspace_id and w_tenant == tenant_id:
        return "unchanged"  # an already mapped pair stays valid even if the organization is paused later
    if t_status != "active":
        return "conflict_tenant_not_active"
    if t_ws not in (None, workspace_id):
        return "conflict_tenant_mapped_elsewhere"
    if w_tenant not in (None, tenant_id):
        return "conflict_workspace_taken"
    return "map" if t_ws is None and w_tenant is None else "complete"


def build_mapping_report(many_conn: Any, saas_conn: Any, pairs: list[tuple[str, str]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for tenant_id, workspace_id in pairs:
        with saas_conn.cursor() as cur:
            cur.execute("SELECT status, many_workspace_id FROM tenants WHERE id = %s", (tenant_id,))
            tenant = cur.fetchone()
        with many_conn.cursor() as cur:
            cur.execute("SELECT saas_tenant_id FROM workspaces WHERE id = %s", (workspace_id,))
            workspace = cur.fetchone()
        rows.append({
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "action": _classify_pair(tenant, workspace, tenant_id, workspace_id),
            "tenant_status": None if tenant is None else tenant[0],
            "tenant_points_at": None if tenant is None else _uuid_text(tenant[1]),
            "workspace_points_at": None if workspace is None else _uuid_text(workspace[0]),
        })
    conflicts = sum(1 for r in rows if r["action"].startswith("conflict_"))
    summary = {
        "pairs": len(rows),
        "to_map": sum(1 for r in rows if r["action"] == "map"),
        "to_complete": sum(1 for r in rows if r["action"] == "complete"),
        "unchanged": sum(1 for r in rows if r["action"] == "unchanged"),
        "conflicts": conflicts,
        "ok_to_apply": conflicts == 0,
    }
    body = {"pairs": rows, "summary": summary}
    return {**body, "report_hash": report_hash(body)}


def apply_mapping(
    many_conn: Any,
    saas_conn: Any,
    pairs: list[tuple[str, str]],
    *,
    expected_hash: str,
    confirm_databases: str,
) -> dict[str, int]:
    """Refuse unless the databases still match the reviewed report and it has no conflict, then map.

    The two databases cannot share a transaction, so the Many side is written first and the SaaS
    side second, each only where it is still empty. A run that stops in between leaves a "complete"
    pair that the next run finishes; nothing is ever overwritten.
    """
    names = f"{db_name(many_conn)},{db_name(saas_conn)}"
    if confirm_databases != names:
        raise Refused(f"--confirm-databases must be exactly {names!r}")
    for label, conn in (("Many", many_conn), ("SaaS", saas_conn)):
        if not try_lock(conn):
            raise Refused(f"another migration holds the {label} advisory lock")
    try:
        report = build_mapping_report(many_conn, saas_conn, pairs)
        if report["report_hash"] != expected_hash:
            raise Refused("the databases no longer match the reviewed report (hash differs)")
        if not report["summary"]["ok_to_apply"]:
            raise Refused("the report has conflicts; nothing was written")
        counts: Counter[str] = Counter()
        for row in report["pairs"]:
            action, tenant_id, workspace_id = row["action"], row["tenant_id"], row["workspace_id"]
            if action == "unchanged":
                counts["unchanged"] += 1
                continue
            with many_conn.cursor() as cur:
                cur.execute(
                    "UPDATE workspaces SET saas_tenant_id = %s WHERE id = %s AND saas_tenant_id IS NULL",
                    (tenant_id, workspace_id),
                )
            many_conn.commit()
            with saas_conn.cursor() as cur:
                cur.execute(
                    "UPDATE tenants SET many_workspace_id = %s WHERE id = %s AND many_workspace_id IS NULL",
                    (workspace_id, tenant_id),
                )
            saas_conn.commit()
            counts["mapped" if action == "map" else "completed"] += 1
        return {"mapped": counts["mapped"], "completed": counts["completed"], "unchanged": counts["unchanged"]}
    finally:
        unlock(many_conn)
        unlock(saas_conn)


def verify_mapping(many_conn: Any, saas_conn: Any) -> dict[str, Any]:
    """Read-only: every mapped organization and workspace must point at each other."""
    with saas_conn.cursor() as cur:
        cur.execute("SELECT id, many_workspace_id FROM tenants")
        tenants = {str(i): _uuid_text(w) for i, w in cur.fetchall()}
    with many_conn.cursor() as cur:
        cur.execute("SELECT id, saas_tenant_id FROM workspaces")
        workspaces = {str(i): _uuid_text(t) for i, t in cur.fetchall()}
    problems: list[str] = []
    mapped = 0
    for tenant_id, workspace_id in tenants.items():
        if workspace_id is None:
            continue
        if workspace_id not in workspaces:
            problems.append(f"organization {tenant_id} points at a missing workspace {workspace_id}")
        elif workspaces[workspace_id] != tenant_id:
            problems.append(f"organization {tenant_id} and workspace {workspace_id} do not point at each other")
        else:
            mapped += 1
    for workspace_id, tenant_id in workspaces.items():
        if tenant_id is not None and tenant_id not in tenants:
            problems.append(f"workspace {workspace_id} points at a missing organization {tenant_id}")
    return {"ok": not problems, "mapped": mapped, "problems": problems}


# --- command line -------------------------------------------------------------------------------


def _connect(env_name: str) -> Any:
    url = os.environ.get(env_name)
    if not url:
        raise SystemExit(f"{env_name} is not set")
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("psycopg is required") from exc
    plain = url.replace("postgresql+psycopg://", "postgresql://")
    return psycopg.connect(plain)


def _safe_out_path(raw: str, *, allow_in_repo: bool) -> Path:
    path = Path(raw).resolve()
    if not allow_in_repo and (path == REPO_ROOT or REPO_ROOT in path.parents):
        raise SystemExit("refusing to write a report with emails inside the repository checkout")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    rep = sub.add_parser("report", help="read-only inventory and match report (default)")
    rep.add_argument("--out", help="write the full report (contains emails) to this path")
    rep.add_argument("--allow-in-repo", action="store_true", help=argparse.SUPPRESS)
    app = sub.add_parser("apply", help="write the links from a reviewed report")
    app.add_argument("--report-hash", required=True)
    app.add_argument("--confirm-databases", required=True, help="'<many_db>,<saas_db>' typed out")
    app.add_argument("--yes", action="store_true", help="I took a backup and reviewed the report")
    sub.add_parser("verify", help="read-only post-checks")
    mrep = sub.add_parser("map-report", help="read-only: classify the owner's organization to workspace pairs")
    mrep.add_argument("--mapping", required=True, help="JSON file of {tenant_id, workspace_id} pairs")
    mapp = sub.add_parser("map-apply", help="write the reviewed mapping to both databases")
    mapp.add_argument("--mapping", required=True)
    mapp.add_argument("--report-hash", required=True)
    mapp.add_argument("--confirm-databases", required=True, help="'<many_db>,<saas_db>' typed out")
    mapp.add_argument("--yes", action="store_true", help="I took a backup and reviewed the report")
    sub.add_parser("verify-mapping", help="read-only: both sides of every mapping agree")
    args = parser.parse_args(argv)

    many_conn, saas_conn = _connect("MANY_DATABASE_URL"), _connect("SAAS_DATABASE_URL")
    print(f"Many database: {db_name(many_conn)}   SaaS database: {db_name(saas_conn)}")
    try:
        if args.command == "report":
            out = _safe_out_path(args.out, allow_in_repo=args.allow_in_repo) if args.out else None
            report = build_report(inventory_many(many_conn), inventory_saas(saas_conn))
            print(json.dumps({"report_hash": report["report_hash"], **report["summary"]}, indent=2))
            if out is not None:
                out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
                print(f"full report written to {out}")
            print("Dry run: nothing was written to either database.")
            return 0
        if args.command == "apply":
            if not args.yes:
                raise SystemExit("apply needs --yes (backup taken, report reviewed)")
            print(json.dumps(apply_report(many_conn, saas_conn, expected_hash=args.report_hash, confirm_databases=args.confirm_databases), indent=2))
            return 0
        if args.command == "map-report":
            report = build_mapping_report(many_conn, saas_conn, load_mapping(Path(args.mapping)))
            print(json.dumps(report, indent=2))
            print("Dry run: nothing was written to either database.")
            return 0 if report["summary"]["ok_to_apply"] else 1
        if args.command == "map-apply":
            if not args.yes:
                raise SystemExit("map-apply needs --yes (backup taken, report reviewed)")
            print(json.dumps(apply_mapping(many_conn, saas_conn, load_mapping(Path(args.mapping)),
                                           expected_hash=args.report_hash,
                                           confirm_databases=args.confirm_databases), indent=2))
            return 0
        if args.command == "verify-mapping":
            result = verify_mapping(many_conn, saas_conn)
            print(json.dumps(result, indent=2))
            return 0 if result["ok"] else 1
        result = verify(many_conn, saas_conn)
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1
    except Refused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    finally:
        many_conn.close()
        saas_conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
