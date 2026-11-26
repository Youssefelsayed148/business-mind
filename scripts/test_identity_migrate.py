"""Tests for scripts/identity_migrate.py. Synthetic data only, throwaway databases only.

Run (needs a disposable Postgres; APP_ENV=test and TEST_DATABASE_URL set explicitly):
  APP_ENV=test TEST_DATABASE_URL=postgresql://user:pass@host/postgres_test \
      python -m pytest scripts/test_identity_migrate.py

Two scratch databases whose names end in _test are created next to the given one and
dropped afterwards. The tests never touch any other database.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import identity_migrate as im  # noqa: E402

psycopg = pytest.importorskip("psycopg")
argon2 = pytest.importorskip("argon2")

MANY_SCHEMA = """
CREATE TABLE users (
    id uuid PRIMARY KEY, email varchar(255) NOT NULL, name text,
    password_hash varchar(255) NOT NULL, role varchar(50) NOT NULL DEFAULT 'admin',
    is_active boolean NOT NULL DEFAULT true, sso_subject uuid UNIQUE,
    auth_source varchar(20) NOT NULL DEFAULT 'local');
CREATE TABLE user_workspace_memberships (
    user_id uuid NOT NULL, workspace_id uuid NOT NULL, role text NOT NULL, source text);
CREATE TABLE workspaces (id uuid PRIMARY KEY, name text, saas_tenant_id uuid UNIQUE);
"""
SAAS_SCHEMA = """
CREATE TABLE users (
    id uuid PRIMARY KEY, email text NOT NULL UNIQUE, password_hash text NOT NULL,
    is_active boolean NOT NULL DEFAULT true, is_platform_staff boolean NOT NULL DEFAULT false,
    legacy_many_user_id uuid UNIQUE);
CREATE TABLE memberships (
    tenant_id uuid NOT NULL, user_id uuid NOT NULL, role text NOT NULL, org_role text,
    status text NOT NULL DEFAULT 'active');
CREATE TABLE tenants (id uuid PRIMARY KEY, name text, status text NOT NULL DEFAULT 'active',
    many_workspace_id uuid UNIQUE);
"""


def _admin_params() -> dict[str, Any]:
    url = os.environ.get("TEST_DATABASE_URL")
    if os.environ.get("APP_ENV") != "test" or not url:
        pytest.skip("APP_ENV=test and TEST_DATABASE_URL must be set explicitly")
    from psycopg.conninfo import conninfo_to_dict

    return conninfo_to_dict(url.replace("postgresql+psycopg://", "postgresql://"))


def _connect(name: str) -> Any:
    from psycopg.conninfo import make_conninfo

    params = _admin_params()
    return psycopg.connect(make_conninfo("", **{**params, "dbname": name}))


@pytest.fixture
def dbs() -> Iterator[tuple[Any, Any, str, str]]:
    params = _admin_params()
    suffix = uuid.uuid4().hex[:8]
    many_name, saas_name = f"idm_many_{suffix}_test", f"idm_saas_{suffix}_test"
    from psycopg.conninfo import make_conninfo

    admin = psycopg.connect(make_conninfo("", **{**params, "dbname": "postgres"}), autocommit=True)
    print(f"host={params.get('host', 'default')} databases={many_name},{saas_name}")
    for name in (many_name, saas_name):
        assert name.endswith("_test")
        admin.execute(f'CREATE DATABASE "{name}"')
    many, saas = _connect(many_name), _connect(saas_name)
    many.execute(MANY_SCHEMA)
    saas.execute(SAAS_SCHEMA)
    many.commit()
    saas.commit()
    try:
        yield many, saas, many_name, saas_name
    finally:
        many.close()
        saas.close()
        for name in (many_name, saas_name):
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.close()


def argon(kind: str = "id") -> str:
    from argon2 import PasswordHasher, Type

    hasher = PasswordHasher(type={"id": Type.ID, "i": Type.I, "d": Type.D}[kind])
    return hasher.hash(f"synthetic-{uuid.uuid4().hex}")


BCRYPT = "$2b$12$" + "a" * 53
PBKDF2 = "$pbkdf2-sha256$29000$c29tZXNhbHQ$" + "b" * 43


def add_many(conn: Any, email: str, password_hash: str, *, role: str = "viewer", active: bool = True,
             sso_subject: str | None = None, source: str = "local") -> str:
    user_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO users (id, email, password_hash, role, is_active, sso_subject, auth_source)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (user_id, email, password_hash, role, active, sso_subject, source),
    )
    conn.commit()
    return user_id


def add_saas(conn: Any, email: str, *, staff: bool = False, active: bool = True,
             legacy: str | None = None, password_hash: str | None = None) -> str:
    user_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO users (id, email, password_hash, is_active, is_platform_staff,"
        " legacy_many_user_id) VALUES (%s,%s,%s,%s,%s,%s)",
        (user_id, email, password_hash or argon(), active, staff, legacy),
    )
    conn.commit()
    return user_id


# --- pure helpers ----------------------------------------------------------------------------


def test_normalization_follows_the_design() -> None:
    assert im.normalize_email("  Person@Example.COM ") == "person@example.com"
    assert im.normalize_email("ＰＥＲＳＯＮ@example.com") == "person@example.com"  # NFKC
    assert im.normalize_email("user@bücher.example") == "user@xn--bcher-kva.example"  # IDNA
    # Dots and +tags are NOT stripped: that would merge different people.
    assert im.normalize_email("a.b+tag@example.com") == "a.b+tag@example.com"
    assert im.normalize_email("a.b+tag@example.com") != im.normalize_email("ab@example.com")


def test_hash_info_reports_algorithm_and_parameters_never_the_hash() -> None:
    good = argon("id")
    info = im.hash_info(good)
    assert info["algorithm"] == "argon2id" and info["carriable"] is True
    assert info["params"] == "v=19,m=65536,t=3,p=4"
    assert good not in json.dumps(info)
    for other, algorithm in (
        (argon("i"), "argon2i"),
        (argon("d"), "argon2d"),
        (BCRYPT, "bcrypt"),
        (PBKDF2, "pbkdf2-sha256"),
        ("", "empty"),
        ("$argon2id$not-a-real-hash", "argon2-malformed"),
        ("plaintext-password", "unknown"),
    ):
        result = im.hash_info(other)
        assert (result["algorithm"], result["carriable"]) == (algorithm, False), other
    weak = "$argon2id$v=19$m=64,t=1,p=1$" + base64.b64encode(b"saltsalt").decode().rstrip("=") + "$" + base64.b64encode(b"x" * 16).decode().rstrip("=")
    assert im.hash_info(weak)["carriable"] is False  # cost below the accepted floor


def test_passlib_and_argon2_cffi_hashes_are_interchangeable() -> None:
    """Design 7.3: Many hashes with passlib, the SaaS verifies with argon2-cffi (and back)."""
    passlib_hash = pytest.importorskip("passlib.hash")
    from argon2 import PasswordHasher

    hasher = PasswordHasher()
    theirs = passlib_hash.argon2.hash("correct horse battery staple")
    assert im.hash_info(theirs)["carriable"] is True
    assert hasher.verify(theirs, "correct horse battery staple")
    ours = hasher.hash("another synthetic password")
    assert passlib_hash.argon2.verify("another synthetic password", ours)
    assert hasher.check_needs_rehash(theirs) in (True, False)  # must not raise


def test_unusable_hash_is_well_formed_and_random() -> None:
    first, second = im.unusable_hash(), im.unusable_hash()
    assert first != second and im.hash_info(first)["carriable"] is True


# --- dataset ----------------------------------------------------------------------------------


def seed(many: Any, saas: Any) -> dict[str, Any]:
    ids: dict[str, Any] = {}
    ids["carry_hash"] = argon()
    ids["carry"] = add_many(many, "Carry@Example.com", ids["carry_hash"])
    ids["bcrypt"] = add_many(many, "bcrypt@example.com", BCRYPT)
    ids["both_many"] = add_many(many, "both@example.com", argon())
    ids["both_saas_hash"] = argon()
    ids["both_saas"] = add_saas(saas, "BOTH@example.com", password_hash=ids["both_saas_hash"])
    add_many(many, "Dup@Example.com", argon())
    add_many(many, "dup@example.com", argon())
    add_many(many, "mixed@example.com", argon(), active=True)
    add_saas(saas, "mixed@example.com", active=False)
    add_many(many, "adminmix@example.com", argon(), role="admin")
    add_saas(saas, "adminmix@example.com", staff=False)
    linked_saas = add_saas(saas, "linked@example.com")
    linked_many = add_many(many, "linked@example.com", argon(), sso_subject=linked_saas, source="sso")
    saas.execute("UPDATE users SET legacy_many_user_id = %s WHERE id = %s", (linked_many, linked_saas))
    saas.commit()
    ids["half_saas"] = add_saas(saas, "half@example.com")
    ids["half_many"] = add_many(many, "half@example.com", argon(), sso_subject=ids["half_saas"], source="sso")
    add_saas(saas, "saas-only@example.com")
    many.execute("INSERT INTO user_workspace_memberships VALUES (%s, %s, 'operator', 'local')", (ids["carry"], str(uuid.uuid4())))
    many.commit()
    return ids


def report_of(many: Any, saas: Any) -> dict[str, Any]:
    return im.build_report(im.inventory_many(many), im.inventory_saas(saas))


def by_email(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["email"]: row for row in report["users"]}


def test_report_classifies_every_case_and_names_every_many_hash(
    dbs: tuple[Any, Any, str, str],
) -> None:
    many, saas, *_ = dbs
    ids = seed(many, saas)
    report = report_of(many, saas)
    rows = by_email(report)
    assert {e: (r["class"], r["action"]) for e, r in rows.items()} == {
        "carry@example.com": ("many_only", "create_saas_user_carry_hash"),
        "bcrypt@example.com": ("many_only", "create_saas_user_needs_set_password_link"),
        "both@example.com": ("both", "link_keep_saas_password"),
        "dup@example.com": ("many_duplicates", "skip"),
        "mixed@example.com": ("both_with_conflicts", "skip"),
        "adminmix@example.com": ("both_with_conflicts", "skip"),
        "linked@example.com": ("both_linked", "none"),
        "half@example.com": ("both_half_linked", "complete_link"),
        "saas-only@example.com": ("saas_only", "none"),
    }
    assert rows["bcrypt@example.com"]["flags"] == ["needs set-password link"]
    assert "inactive on one side" in rows["mixed@example.com"]["flags"]
    assert any("owner decision" in f for f in rows["adminmix@example.com"]["flags"])
    summary = report["summary"]
    assert summary["many_users"] == 9 and summary["saas_users"] == 6
    assert summary["needs_set_password_link"] == 1
    # The hash algorithm of EVERY Many user row is in the report.
    listed = [h for r in report["users"] for h in r["many_hashes"]]
    assert len(listed) == summary["many_users"] == 9
    assert all(h["algorithm"] for h in listed)
    assert summary["many_hash_algorithms"] == {"argon2id": 8, "bcrypt": 1}
    assert next(h for h in rows["carry@example.com"]["many_hashes"])["params"] == "v=19,m=65536,t=3,p=4"
    assert rows["carry@example.com"]["many_workspace_roles"] == [["operator"]]
    # No hash, password or salt anywhere in the report.
    blob = json.dumps(report)
    raw = [ids["carry_hash"], ids["both_saas_hash"], BCRYPT]
    assert not any(value in blob for value in raw) and "$argon2" not in blob and "$2b$" not in blob


def test_the_report_hash_is_stable_and_tracks_the_data(dbs: tuple[Any, Any, str, str]) -> None:
    many, saas, *_ = dbs
    seed(many, saas)
    first = report_of(many, saas)["report_hash"]
    assert report_of(many, saas)["report_hash"] == first
    add_many(many, "late@example.com", argon())
    assert report_of(many, saas)["report_hash"] != first


def snapshot(*conns: Any) -> list[list[tuple[Any, ...]]]:
    out = []
    for conn in conns:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users ORDER BY id")
            out.append(cur.fetchall())
    return out


def test_report_is_read_only(dbs: tuple[Any, Any, str, str], tmp_path: Path,
                              monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    many, saas, many_name, saas_name = dbs
    seed(many, saas)
    before = snapshot(many, saas)
    from psycopg.conninfo import make_conninfo

    params = _admin_params()
    monkeypatch.setenv("MANY_DATABASE_URL", make_conninfo("", **{**params, "dbname": many_name}))
    monkeypatch.setenv("SAAS_DATABASE_URL", make_conninfo("", **{**params, "dbname": saas_name}))
    out = tmp_path / "report.json"
    assert im.main(["report", "--out", str(out)]) == 0
    shown = capsys.readouterr().out
    assert many_name in shown and saas_name in shown and "Dry run" in shown
    assert str(params.get("password", "no-password-set")) not in shown or not params.get("password")
    assert json.loads(out.read_text(encoding="utf-8"))["summary"]["many_users"] == 9
    assert snapshot(many, saas) == before


def test_a_report_with_emails_cannot_be_written_inside_the_repository() -> None:
    with pytest.raises(SystemExit):
        im._safe_out_path(str(im.REPO_ROOT / "report.json"), allow_in_repo=False)
    im._safe_out_path(str(im.REPO_ROOT / "report.json"), allow_in_repo=True)


def run_apply(dbs: tuple[Any, Any, str, str], *, report_hash: str | None = None,
              confirm: str | None = None) -> dict[str, int]:
    many, saas, many_name, saas_name = dbs
    return im.apply_report(
        many, saas,
        expected_hash=report_hash or report_of(many, saas)["report_hash"],
        confirm_databases=confirm or f"{many_name},{saas_name}",
    )


def test_apply_refuses_without_the_exact_reviewed_report_and_typed_names(
    dbs: tuple[Any, Any, str, str],
) -> None:
    many, saas, many_name, saas_name = dbs
    seed(many, saas)
    before = snapshot(many, saas)
    with pytest.raises(im.Refused):
        run_apply(dbs, report_hash="0" * 64)
    with pytest.raises(im.Refused):
        run_apply(dbs, confirm=f"{saas_name},{many_name}")  # wrong order
    with pytest.raises(im.Refused):
        run_apply(dbs, confirm="production,production")
    assert snapshot(many, saas) == before
    # Data changed after the owner reviewed: the old hash no longer applies.
    reviewed = report_of(many, saas)["report_hash"]
    add_many(many, "after-review@example.com", argon())
    with pytest.raises(im.Refused):
        run_apply(dbs, report_hash=reviewed)


def test_apply_links_carries_or_withholds_and_leaves_conflicts_alone(
    dbs: tuple[Any, Any, str, str],
) -> None:
    many, saas, *_ = dbs
    ids = seed(many, saas)
    counts = run_apply(dbs)
    assert counts == {"created_carried": 1, "created_needs_link": 1, "linked": 1, "completed": 1,
                      "skipped": 3, "unchanged": 2}
    with saas.cursor() as cur:
        cur.execute("SELECT id, password_hash, is_active, is_platform_staff, legacy_many_user_id FROM users WHERE email = 'carry@example.com'")
        carried = cur.fetchone()
        cur.execute("SELECT password_hash, legacy_many_user_id FROM users WHERE email = 'bcrypt@example.com'")
        withheld = cur.fetchone()
        cur.execute("SELECT password_hash, legacy_many_user_id FROM users WHERE id = %s", (ids["both_saas"],))
        kept = cur.fetchone()
        cur.execute("SELECT count(*) FROM users WHERE is_platform_staff")
        staff_count = cur.fetchone()[0]
    assert carried[1] == ids["carry_hash"] and str(carried[4]) == ids["carry"]  # the argon2id hash was carried
    assert carried[3] is False and staff_count == 0  # nobody became staff
    assert withheld[0] != BCRYPT and im.hash_info(withheld[0])["algorithm"] == "argon2id"  # never carried
    assert str(withheld[1]) == ids["bcrypt"]
    assert kept[0] == ids["both_saas_hash"] and str(kept[1]) == ids["both_many"]  # SaaS password kept
    with many.cursor() as cur:
        cur.execute("SELECT id, password_hash, sso_subject, auth_source FROM users")
        rows = {str(r[0]): r for r in cur.fetchall()}
    for key in ("carry", "bcrypt", "both_many", "half_many"):
        row = rows[ids[key]]
        assert row[2] is not None and row[3] == "sso"
        assert row[1] != ids["carry_hash"] and im.hash_info(row[1])["carriable"]  # replaced by an unusable hash
    skipped = [r for r in rows.values() if r[2] is None]
    assert len(skipped) == 4 and all(r[3] == "local" for r in skipped)  # 2 duplicates + 2 conflicts untouched
    after = im.verify(many, saas)
    assert after["ok"] is True and after["linked"] == 5 and after["many_users_not_linked"] == 4


def test_apply_is_idempotent(dbs: tuple[Any, Any, str, str]) -> None:
    many, saas, *_ = dbs
    seed(many, saas)
    run_apply(dbs)
    once = snapshot(many, saas)
    second = run_apply(dbs)
    assert set(second) <= {"unchanged", "skipped"}
    assert snapshot(many, saas) == once
    report = report_of(many, saas)
    assert report["summary"]["actions"].get("create_saas_user_carry_hash") is None


def test_apply_takes_a_lock_and_refuses_when_another_run_holds_it(
    dbs: tuple[Any, Any, str, str],
) -> None:
    many, saas, many_name, _saas_name = dbs
    seed(many, saas)
    other = _connect(many_name)
    try:
        assert im.try_lock(other)
        before = snapshot(many, saas)
        with pytest.raises(im.Refused) as error:
            run_apply(dbs)
        assert "advisory lock" in str(error.value)
        assert snapshot(many, saas) == before
    finally:
        im.unlock(other)
        other.close()
    run_apply(dbs)  # the lock is released after a refused or finished run


def test_verify_finds_broken_links(dbs: tuple[Any, Any, str, str]) -> None:
    many, saas, *_ = dbs
    ids = seed(many, saas)
    run_apply(dbs)
    saas.execute("UPDATE users SET legacy_many_user_id = NULL WHERE id = %s", (ids["both_saas"],))
    saas.commit()
    result = im.verify(many, saas)
    assert result["ok"] is False and any("do not point at each other" in p for p in result["problems"])


# --- organization to workspace mapping (Phase 4A, design 4.1) ----------------------------------


def add_tenant(conn: Any, *, status: str = "active", workspace: str | None = None) -> str:
    tenant_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO tenants (id, name, status, many_workspace_id) VALUES (%s,%s,%s,%s)",
        (tenant_id, "Org " + tenant_id[:4], status, workspace),
    )
    conn.commit()
    return tenant_id


def add_workspace(conn: Any, *, tenant: str | None = None) -> str:
    workspace_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO workspaces (id, name, saas_tenant_id) VALUES (%s,%s,%s)",
        (workspace_id, "WS " + workspace_id[:4], tenant),
    )
    conn.commit()
    return workspace_id


def map_state(many: Any, saas: Any) -> tuple[list[Any], list[Any]]:
    return (
        saas.execute("SELECT id, many_workspace_id FROM tenants ORDER BY id").fetchall(),
        many.execute("SELECT id, saas_tenant_id FROM workspaces ORDER BY id").fetchall(),
    )


def map_report(dbs: tuple[Any, Any, str, str], pairs: list[tuple[str, str]]) -> dict[str, Any]:
    many, saas, _, _ = dbs
    return im.build_mapping_report(many, saas, pairs)


def map_apply(dbs: tuple[Any, Any, str, str], pairs: list[tuple[str, str]], *, report_hash: str | None = None,
              confirm: str | None = None) -> dict[str, int]:
    many, saas, many_name, saas_name = dbs
    return im.apply_mapping(
        many, saas, pairs,
        expected_hash=report_hash or map_report(dbs, pairs)["report_hash"],
        confirm_databases=confirm or f"{many_name},{saas_name}",
    )


def test_mapping_file_is_validated(tmp_path: Path) -> None:
    good = tmp_path / "ok.json"
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    good.write_text(json.dumps([{"tenant_id": a, "workspace_id": b}]))
    assert im.load_mapping(good) == [(a, b)]
    for bad in (
        "not json",
        json.dumps({"tenant_id": a}),
        json.dumps([{"tenant_id": "nope", "workspace_id": b}]),
        json.dumps([{"tenant_id": a, "workspace_id": b}, {"tenant_id": a, "workspace_id": str(uuid.uuid4())}]),
        json.dumps([{"tenant_id": a, "workspace_id": b}, {"tenant_id": str(uuid.uuid4()), "workspace_id": b}]),
        json.dumps([{"tenant_id": a, "workspace_id": b, "extra": 1}]),
        json.dumps([]),
    ):
        path = tmp_path / "bad.json"
        path.write_text(bad)
        with pytest.raises(im.Refused):
            im.load_mapping(path)


def test_mapping_report_classifies_every_case_and_writes_nothing(dbs: tuple[Any, Any, str, str]) -> None:
    many, saas, _, _ = dbs
    t_new, w_new = add_tenant(saas), add_workspace(many)
    w_done = add_workspace(many)
    t_done = add_tenant(saas, workspace=w_done)
    many.execute("UPDATE workspaces SET saas_tenant_id = %s WHERE id = %s", (t_done, w_done))
    many.commit()
    w_half = add_workspace(many)
    t_half = add_tenant(saas, workspace=w_half)  # SaaS side set, Many side still empty
    t_other, w_other = add_tenant(saas), add_workspace(many)
    t_taken = add_tenant(saas, workspace=w_other)
    many.execute("UPDATE workspaces SET saas_tenant_id = %s WHERE id = %s", (t_taken, w_other))
    many.commit()
    t_paused = add_tenant(saas, status="suspended")
    w_for_paused = add_workspace(many)
    pairs = [
        (t_new, w_new),
        (t_done, w_done),
        (t_half, w_half),
        (t_other, w_other),  # workspace already belongs to another tenant
        (str(uuid.uuid4()), add_workspace(many)),  # tenant does not exist
        (add_tenant(saas), str(uuid.uuid4())),  # workspace does not exist
        (t_paused, w_for_paused),  # tenant not active
    ]
    before = map_state(many, saas)
    report = map_report(dbs, pairs)
    actions = [row["action"] for row in report["pairs"]]
    assert actions == [
        "map", "unchanged", "complete", "conflict_workspace_taken",
        "conflict_tenant_missing", "conflict_workspace_missing", "conflict_tenant_not_active",
    ]
    assert report["summary"]["conflicts"] == 4 and report["summary"]["ok_to_apply"] is False
    assert map_state(many, saas) == before


def test_mapping_report_hash_tracks_the_data(dbs: tuple[Any, Any, str, str]) -> None:
    many, saas, _, _ = dbs
    pairs = [(add_tenant(saas), add_workspace(many))]
    first = map_report(dbs, pairs)["report_hash"]
    assert first == map_report(dbs, pairs)["report_hash"]
    add_tenant(saas)  # unrelated rows do not change this report
    assert first == map_report(dbs, pairs)["report_hash"]
    saas.execute("UPDATE tenants SET status = 'suspended' WHERE id = %s", (pairs[0][0],))
    saas.commit()
    assert first != map_report(dbs, pairs)["report_hash"]


def test_mapping_apply_refuses_with_conflicts_wrong_hash_or_names(dbs: tuple[Any, Any, str, str]) -> None:
    many, saas, many_name, saas_name = dbs
    good = (add_tenant(saas), add_workspace(many))
    bad = (str(uuid.uuid4()), add_workspace(many))
    before = map_state(many, saas)
    with pytest.raises(im.Refused):
        map_apply(dbs, [good, bad])  # a conflict blocks the whole run
    with pytest.raises(im.Refused):
        map_apply(dbs, [good], report_hash="0" * 64)
    with pytest.raises(im.Refused):
        map_apply(dbs, [good], confirm=f"{saas_name},{many_name}")
    assert map_state(many, saas) == before


def test_mapping_apply_sets_both_sides_and_is_idempotent(dbs: tuple[Any, Any, str, str]) -> None:
    many, saas, _, _ = dbs
    t1, w1 = add_tenant(saas), add_workspace(many)
    w2 = add_workspace(many)
    t2 = add_tenant(saas, workspace=w2)  # half done: SaaS side only
    pairs = [(t1, w1), (t2, w2)]
    assert map_apply(dbs, pairs) == {"mapped": 1, "completed": 1, "unchanged": 0}
    assert saas.execute("SELECT many_workspace_id FROM tenants WHERE id = %s", (t1,)).fetchone()[0] == uuid.UUID(w1)
    assert many.execute("SELECT saas_tenant_id FROM workspaces WHERE id = %s", (w1,)).fetchone()[0] == uuid.UUID(t1)
    assert many.execute("SELECT saas_tenant_id FROM workspaces WHERE id = %s", (w2,)).fetchone()[0] == uuid.UUID(t2)
    state = map_state(many, saas)
    assert map_apply(dbs, pairs) == {"mapped": 0, "completed": 0, "unchanged": 2}
    assert map_state(many, saas) == state


def test_mapping_apply_takes_a_lock(dbs: tuple[Any, Any, str, str]) -> None:
    many, saas, many_name, saas_name = dbs
    pairs = [(add_tenant(saas), add_workspace(many))]
    reviewed = map_report(dbs, pairs)["report_hash"]
    other = _connect(many_name)
    assert im.try_lock(other)
    try:
        with pytest.raises(im.Refused):
            map_apply(dbs, pairs, report_hash=reviewed)
    finally:
        im.unlock(other)
        other.close()
    assert saas.execute("SELECT many_workspace_id FROM tenants").fetchone()[0] is None


def test_verify_reports_one_sided_and_mismatched_mappings(dbs: tuple[Any, Any, str, str]) -> None:
    many, saas, _, _ = dbs
    w1 = add_workspace(many)
    t1 = add_tenant(saas, workspace=w1)  # Many side missing
    w2 = add_workspace(many)
    add_tenant(saas, workspace=w2)
    many.execute("UPDATE workspaces SET saas_tenant_id = %s WHERE id = %s", (str(uuid.uuid4()), w2))  # wrong tenant
    many.commit()
    result = im.verify_mapping(many, saas)
    assert result["ok"] is False
    assert any(t1 in problem for problem in result["problems"])
    assert len(result["problems"]) == 3  # one-sided tenant, mismatched tenant, dangling workspace pointer
