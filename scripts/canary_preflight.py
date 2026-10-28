"""Read-only, local-only canary checks; never load settings or env files.

Run with the backend's installed dependencies. Only the DB check imports app
models and existing SQLAlchemy/psycopg dependencies. No HTTP, DNS or Redis calls.
"""

from __future__ import annotations

import argparse
import ast
import ipaddress
from collections import Counter
import os
from pathlib import Path
import re
import sys
from uuid import UUID
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_REVISIONS = (
    "0023_saas_delegation", "0024_saas_forward_events",
    "0025_saas_outbound_messages", "0026_saas_channel_health",
    "0027_saas_conn_id_lowercase",
)
REQUIRED_TASKS = {
    "app.workers.saas_forward_tasks.sweep_saas_forwards",
    "app.workers.saas_send_tasks.sweep_saas_sends",
    "app.workers.saas_health_tasks.sweep_saas_health",
    "app.workers.saas_retention_tasks.purge_saas_data",
}


class CheckFailed(ValueError):
    """A fixed, non-sensitive diagnostic safe to print."""


def assignments(tree: ast.AST, name: str) -> list[ast.expr]:
    values = []
    for node in ast.walk(tree):
        targets = node.targets if isinstance(node, ast.Assign) else (
            [node.target] if isinstance(node, ast.AnnAssign) else []
        )
        if any(ast.unparse(target) == name for target in targets):
            values.append(node.value)
    return values


def parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8-sig"))


def migration_head(root: Path) -> str:
    """Read revision metadata without importing migrations or alembic/env.py."""
    parents: dict[str, str | None] = {}
    for path in (root / "backend/alembic/versions").glob("*.py"):
        tree = parse(path)
        revisions, previous = assignments(tree, "revision"), assignments(tree, "down_revision")
        if not revisions and not previous:
            continue
        if len(revisions) != 1 or len(previous) != 1:
            raise CheckFailed("migration metadata is ambiguous")
        revision, parent = ast.literal_eval(revisions[0]), ast.literal_eval(previous[0])
        if not isinstance(revision, str) or not re.fullmatch(r"[a-z0-9_]+", revision):
            raise CheckFailed("invalid migration revision")
        if parent is not None and not isinstance(parent, str):
            raise CheckFailed("branched migration ancestry needs review")
        if revision in parents:
            raise CheckFailed("duplicate migration revision")
        parents[revision] = parent
    heads = set(parents) - set(parents.values())
    if len(heads) != 1:
        raise CheckFailed("expected exactly one Alembic source head")
    head = next(iter(heads))
    chain = []
    current: str | None = head
    while current is not None:
        if current in chain or current not in parents:
            raise CheckFailed("broken migration ancestry")
        chain.append(current)
        current = parents[current]
    if set(chain) != set(parents):
        raise CheckFailed("disconnected migration ancestry")
    required = list(reversed(REQUIRED_REVISIONS))
    if any(revision not in chain for revision in required):
        raise CheckFailed("SaaS migrations 0023-0027 are missing")
    offset = chain.index(required[0])
    if chain[offset:offset + len(required)] != required:
        raise CheckFailed("SaaS migration chain differs from 0023-0027")
    return head


def check_beat(root: Path) -> None:
    """Resolve the source schedule merge without importing settings/Celery."""
    tree = parse(root / "backend/app/workers/celery_app.py")
    schedules = assignments(tree, "celery_app.conf.beat_schedule")
    if len(schedules) != 1 or not isinstance(schedules[0], ast.Dict):
        raise CheckFailed("expected one merged beat_schedule assignment")
    imports = {
        alias.asname or alias.name: (node.module, alias.name)
        for node in tree.body if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    merged: dict[str, str] = {}
    for key, value in zip(schedules[0].keys, schedules[0].values):
        if key is not None:
            raise CheckFailed("inline beat entries need review")
        if ast.unparse(value) == "celery_app.conf.beat_schedule or {}":
            continue  # Celery's initial defaults; no external runtime config inspected.
        if not isinstance(value, ast.Name) or value.id not in imports:
            raise CheckFailed("unknown beat schedule merge")
        module, name = imports[value.id]
        if module is None or not module.startswith("app.workers."):
            raise CheckFailed("unexpected beat schedule import")
        path = root / "backend" / (module.replace(".", "/") + ".py")
        definitions = assignments(parse(path), name)
        if len(definitions) != 1 or not isinstance(definitions[0], ast.Dict):
            raise CheckFailed("schedule definition needs review")
        for entry, config in zip(definitions[0].keys, definitions[0].values):
            if not isinstance(entry, ast.Constant) or not isinstance(entry.value, str):
                raise CheckFailed("nonliteral beat entry")
            if entry.value in merged or not isinstance(config, ast.Dict):
                raise CheckFailed("duplicate or ambiguous beat entry")
            fields = {ast.literal_eval(k): v for k, v in zip(config.keys, config.values)}
            if "task" not in fields or "schedule" not in fields:
                raise CheckFailed("beat entry has no task or schedule")
            merged[entry.value] = ast.literal_eval(fields["task"])
    counts = Counter(merged.values())
    if any(counts[task] != 1 for task in REQUIRED_TASKS):
        raise CheckFailed("each of the four SaaS tasks must appear exactly once")


def check_nginx(path: Path) -> None:
    """Conservative source check, not a substitute for nginx -T/runtime QA."""
    source = re.sub(r"#[^\n]*", "", path.read_text(encoding="utf-8"))
    for prefix in ("/api/saas/", "/saas/"):
        blocks = re.findall(
            r"\blocation\s+(?:\^~\s+)?" + re.escape(prefix) + r"\s*\{([^{}]*)\}", source
        )
        if len(blocks) != 1:
            raise CheckFailed("expected one explicit location for each signed SaaS prefix")
        directives = re.findall(r"\bgzip\s+([^;]+);", blocks[0])
        if [directive.strip() for directive in directives] != ["off"]:
            raise CheckFailed("signed SaaS locations must contain exactly one gzip off")
        if re.search(r"\binclude\b", blocks[0]):
            raise CheckFailed("included SaaS location configuration needs manual review")


def canonical_uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def public_https_base_url(value: object) -> bool:
    """Offline syntax check only; runtime delegation validation also checks DNS."""
    if not isinstance(value, str):
        return False
    try:
        url = urlsplit(value)
        if (url.scheme != "https" or not url.hostname or url.username or url.password
                or url.query or url.fragment):
            return False
        url.port  # Reject malformed port syntax without narrowing the runtime contract.
        host = url.hostname.rstrip(".").lower()
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            return False
        try:
            literal = ipaddress.ip_address(host)
            return literal.is_global and not literal.is_multicast and not literal.is_reserved
        except ValueError:
            return "." in host and all(
                re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in host.split(".")
            )
    except ValueError:
        return False


def check_beat_process_count(count: int | None) -> None:
    """Require an operator-observed count, separately from source scheduling."""
    if count != 1:
        raise CheckFailed("supply --beat-process-count 1 only after observing exactly one running beat")


def check_database(raw_url: str, account_id: UUID, expected_head: str) -> None:
    # These dependencies already belong to the backend; no new packages.
    from sqlalchemy import create_engine, func, select, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.pool import NullPool

    url = make_url(raw_url)
    # Unix sockets only: prohibit DNS, TCP and libpq query overrides.
    if (url.drivername != "postgresql+psycopg" or url.host is not None
            or set(url.query) - {"host", "port"}
            or not isinstance(url.query.get("host"), str)
            or not re.fullmatch(r"/[A-Za-z0-9_./-]+", url.query["host"])
            or not url.database):
        raise CheckFailed("DB URL must use psycopg and one local Unix socket; TCP is refused")
    if os.environ.get("APP_ENV") == "test" and not re.fullmatch(r"many_test(?:_[a-z0-9_]+)?", url.database):
        raise CheckFailed("test mode permits only explicitly named many_test databases")
    sys.path.insert(0, str(ROOT / "backend"))
    from app.models.whatsapp_account import WhatsappAccount

    engine = create_engine(
        url, poolclass=NullPool, echo=False,
        connect_args={"connect_timeout": 5, "options": (
            "-c default_transaction_read_only=on -c statement_timeout=5000"
        )},
    )
    try:
        with engine.connect() as connection:
            with connection.begin():
                connection.execute(text("SET TRANSACTION READ ONLY"))
                versions = list(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
                if versions != [expected_head]:
                    raise CheckFailed("database is not at the single Alembic source head")
                # Never retrieve secret ciphertext: PostgreSQL returns only its presence.
                row = connection.execute(select(
                    WhatsappAccount.saas_connection_id,
                    WhatsappAccount.saas_delegation_enabled,
                    WhatsappAccount.saas_base_url,
                    func.length(func.trim(WhatsappAccount.saas_secret_encrypted)) > 0,
                ).where(WhatsappAccount.id == account_id)).one_or_none()
                if row is None or not canonical_uuid(row[0]):
                    raise CheckFailed("selected WhatsApp account is missing or its connection id is not a lowercase UUID")
                if not row[1] or not public_https_base_url(row[2]) or not row[3]:
                    raise CheckFailed("selected channel needs delegation enabled, a public HTTPS base URL and a stored secret")
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="source tree to inspect")
    parser.add_argument("--nginx-config", type=Path, help="nginx config to inspect (source default)")
    parser.add_argument("--account-id", help="Many WhatsApp account UUID, not SaaS connection UUID")
    parser.add_argument("--database-url-env", default="CANARY_DATABASE_URL", help="explicit URL env name; never DATABASE_URL")
    parser.add_argument("--beat-process-count", type=int, help="operator-observed running beat count across the deployment; must be one")
    parser.add_argument("--static-only", action="store_true", help="no DB access; exits 2 because DB readiness is unverified")
    args = parser.parse_args(argv)
    failed = False
    head = None
    for label, check in (
        ("Alembic source head and 0023-0027 ancestry", lambda: migration_head(args.root)),
        ("single merged beat schedule, four SaaS tasks", lambda: check_beat(args.root)),
        ("nginx signed prefixes gzip off", lambda: check_nginx(args.nginx_config or args.root / "nginx/default.conf")),
    ):
        try:
            result = check()
            if label.startswith("Alembic"):
                head = result
            print(f"PASS: {label}")
        except Exception as exc:
            detail = str(exc) if isinstance(exc, CheckFailed) else "source unavailable or unsupported syntax"
            print(f"FAIL: {label}: {detail}")
            failed = True
    if args.static_only:
        print("UNVERIFIED: database revision and stored connection UUID (static-only)")
        return 1 if failed else 2
    try:
        if head is None:
            raise CheckFailed("source migration head check must pass first")
        if args.database_url_env == "DATABASE_URL" or not re.fullmatch(r"[A-Z][A-Z0-9_]*", args.database_url_env):
            raise CheckFailed("use a dedicated explicit DB URL environment variable")
        raw_url = os.environ.get(args.database_url_env)
        if not raw_url:
            raise CheckFailed("dedicated DB URL environment variable is missing")
        try:
            account_id = UUID(args.account_id or "")
        except ValueError:
            raise CheckFailed("a Many WhatsApp account UUID is required") from None
        check_database(raw_url, account_id, head)
        print("PASS: local read-only DB at head; selected delegation enabled, UUID/HTTPS URL/secret presence valid (DNS unverified)")
        check_beat_process_count(args.beat_process_count)
        print("PASS: operator-observed running beat count is one (source schedule checked separately)")
    except Exception as exc:
        # Never print library exceptions/tracebacks: they may embed a DB URL.
        detail = str(exc) if isinstance(exc, CheckFailed) else "DB check unavailable; verify dependencies, local socket and schema"
        print(f"FAIL: database readiness: {detail}")
        failed = True
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
