"""Verify migration 0015's duplicate-conversation merge.

Why this is a script and not a pytest test: `backend/alembic/` is a regular
package (it has an `__init__.py`), so whenever the suite runs with
PYTHONPATH=backend it shadows the installed `alembic` distribution. A test
therefore cannot `import alembic.migration` to drive the migration, and the
migration module itself does `from alembic import op`. Rather than fake that
up, the merge is verified here, out of process, where alembic resolves
normally.

That also matches how the merge behaves in reality: on a fresh database it is
dead code, because 0001_initial builds tables from the live models -- which
already declare `uq_conversation_lead_cold_dm` -- so duplicates can never
exist by the time 0015 runs. The merge executes exactly once, against a real
production database. This script is the thing that exercises it.

Two modes:

  # Self-contained: build a scratch DB, seed known duplicate groups, run the
  # migration, assert the merged result. Use this to check the migration logic.
  python scripts/verify_0015_merge.py --self-test \
      --admin-dsn postgresql://postgres:PW@localhost:5432/postgres

  # Read-only: point at a restored production snapshot BEFORE deploying and
  # report what the merge would touch. Makes no changes.
  python scripts/verify_0015_merge.py --report \
      --dsn postgresql://postgres:PW@localhost:5432/snapshot

Run from the `backend/` directory, with PYTHONPATH unset (see above).
"""

from __future__ import annotations

import argparse
import datetime
import subprocess
import sys
import uuid

import psycopg

NOW = datetime.datetime(2026, 9, 1, tzinfo=datetime.timezone.utc)

# (name, [(turn_count, status, handoff_reason), ...] oldest first, expected_status,
#  expected_handoff_reason, expected_turn_count)
SCENARIOS = [
    (
        "handed_off duplicate must keep the thread handed off",
        [(2, "bot_active", None), (3, "handed_off", "manual"), (5, "bot_active", None)],
        "handed_off",
        "manual",
        10,
    ),
    (
        "survivor already handed_off is not downgraded",
        [(1, "handed_off", "turn_limit"), (4, "bot_active", None)],
        "handed_off",
        "turn_limit",
        5,
    ),
    (
        "handoff_reason comes from the most recently active fork",
        [(1, "handed_off", "turn_limit"), (2, "handed_off", "user_requested_human")],
        "handed_off",
        "user_requested_human",
        3,
    ),
    (
        "closed outranks handed_off",
        [(1, "handed_off", "manual"), (2, "closed", None)],
        "closed",
        "manual",
        3,
    ),
    (
        "all-active group stays active with no reason",
        [(1, "bot_active", None), (2, "bot_active", None)],
        "bot_active",
        None,
        3,
    ),
]


def _seed(conn: psycopg.Connection) -> list[tuple]:
    ws = uuid.uuid4()
    acc = uuid.uuid4()
    conn.execute("insert into workspaces (id,name,slug) values (%s,'verify','verify-0015')", (ws,))
    conn.execute(
        """insert into instagram_accounts
           (id,workspace_id,ig_user_id,ig_username,status,business_vertical,
            ai_enabled,ai_daily_message_cap,ai_messages_sent_today,ai_cold_dm_enabled)
           values (%s,%s,'ig_verify','verify','connected','general',false,100,0,false)""",
        (acc, ws),
    )

    seeded = []
    for name, spec, exp_status, exp_reason, exp_turns in SCENARIOS:
        lead = uuid.uuid4()
        conn.execute(
            """insert into leads (id,workspace_id,platform,instagram_account_id,ig_user_id,lead_source,status)
               values (%s,%s,'instagram',%s,%s,'cold_dm','new')""",
            (lead, ws, acc, uuid.uuid4().hex),
        )
        ids = []
        for i, (turns, status, reason) in enumerate(spec):
            cid = uuid.uuid4()
            ids.append(cid)
            conn.execute(
                """insert into conversations
                   (id,workspace_id,lead_id,platform,instagram_account_id,status,handoff_reason,
                    turn_count,last_message_at,created_at,updated_at)
                   values (%s,%s,%s,'instagram',%s,%s,%s,%s,%s,%s,%s)""",
                (
                    cid, ws, lead, acc, status, reason, turns,
                    NOW + datetime.timedelta(hours=i),
                    NOW + datetime.timedelta(minutes=i),
                    NOW,
                ),
            )
            for _ in range(2):
                conn.execute(
                    """insert into messages
                       (id,lead_id,conversation_id,direction,message_type,status,retryable,retry_count)
                       values (%s,%s,%s,'inbound','ai_conversation','received',false,0)""",
                    (uuid.uuid4(), lead, cid),
                )
        seeded.append((name, lead, ids, spec, exp_status, exp_reason, exp_turns))
    return seeded


def _check(conn: psycopg.Connection, seeded: list[tuple]) -> bool:
    all_ok = True
    for name, lead, ids, spec, exp_status, exp_reason, exp_turns in seeded:
        rows = list(
            conn.execute(
                "select id,status,handoff_reason,turn_count from conversations where lead_id=%s",
                (lead,),
            )
        )
        msgs = conn.execute(
            "select count(*) from messages where conversation_id = %s", (ids[0],)
        ).fetchone()[0]
        dangling = conn.execute(
            """select count(*) from messages m left join conversations c on c.id = m.conversation_id
               where m.lead_id = %s and m.conversation_id is not null and c.id is null""",
            (lead,),
        ).fetchone()[0]

        ok = (
            len(rows) == 1
            and rows[0][0] == ids[0]
            and rows[0][1] == exp_status
            and rows[0][2] == exp_reason
            and rows[0][3] == exp_turns
            and msgs == len(spec) * 2
            and dangling == 0
        )
        all_ok = all_ok and ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        if not ok:
            print(
                f"         rows={len(rows)} kept_oldest={rows and rows[0][0] == ids[0]} "
                f"status={rows and rows[0][1]!r} (want {exp_status!r}) "
                f"reason={rows and rows[0][2]!r} (want {exp_reason!r}) "
                f"turns={rows and rows[0][3]} (want {exp_turns}) "
                f"msgs={msgs} (want {len(spec) * 2}) dangling={dangling}"
            )
    return all_ok


def self_test(admin_dsn: str, db_name: str) -> int:
    base = admin_dsn.rsplit("/", 1)[0]
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(f'drop database if exists "{db_name}"')
        admin.execute(f'create database "{db_name}"')

    target = f"{base}/{db_name}"
    sa_url = target.replace("postgresql://", "postgresql+psycopg://", 1)

    def alembic(*args: str) -> None:
        env = {"DATABASE_URL": sa_url, "REDIS_URL": "redis://localhost:6379/0"}
        import os

        merged = {**os.environ, **env}
        merged.pop("PYTHONPATH", None)  # see module docstring
        subprocess.run(["alembic", *args], check=True, env=merged, capture_output=True)

    print("1. migrating to 0014 (state just before the merge migration)")
    alembic("upgrade", "0014_facebook_psid")

    print("2. dropping uq_conversation_lead_cold_dm to reproduce a real pre-0015 database")
    with psycopg.connect(target, autocommit=True) as conn:
        conn.execute("drop index if exists uq_conversation_lead_cold_dm")

        print(f"3. seeding {len(SCENARIOS)} duplicate groups")
        seeded = _seed(conn)

    print("4. running 0015")
    alembic("upgrade", "head")

    print("5. checking merged results")
    with psycopg.connect(target) as conn:
        ok = _check(conn, seeded)
        idx = conn.execute(
            "select count(*) from pg_indexes where indexname='uq_conversation_lead_cold_dm'"
        ).fetchone()[0]
        print(f"  [{'PASS' if idx == 1 else 'FAIL'}] partial unique index created")
        ok = ok and idx == 1

    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(f'drop database if exists "{db_name}"')

    print()
    print("RESULT:", "all scenarios passed" if ok else "FAILURES ABOVE")
    return 0 if ok else 1


def report(dsn: str) -> int:
    """Read-only: what would the merge touch on this database?"""
    with psycopg.connect(dsn) as conn:
        groups = list(
            conn.execute(
                """select lead_id, count(*) as n,
                          bool_or(status = 'handed_off') as any_handed_off,
                          bool_or(status = 'closed') as any_closed,
                          sum(turn_count) as total_turns
                   from conversations
                   where campaign_id is null and facebook_campaign_id is null
                   group by lead_id having count(*) > 1
                   order by count(*) desc"""
            )
        )
        print(f"duplicate NULL-campaign conversation groups: {len(groups)}")
        if not groups:
            print("nothing to merge; 0015 will only create the index")
            return 0
        affected = sum(g[1] - 1 for g in groups)
        print(f"conversation rows that would be merged away: {affected}")
        print(f"groups where a fork was handed off/closed:   "
              f"{sum(1 for g in groups if g[2] or g[3])}")
        print()
        print("  lead_id                              rows  handed_off  closed  summed_turns")
        for lead_id, n, ho, cl, turns in groups[:25]:
            print(f"  {lead_id}  {n:>4}  {str(bool(ho)):>10}  {str(bool(cl)):>6}  {turns:>12}")
        if len(groups) > 25:
            print(f"  ... and {len(groups) - 25} more")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true", help="seed a scratch DB and assert the merge")
    mode.add_argument("--report", action="store_true", help="read-only report against an existing DB")
    ap.add_argument("--admin-dsn", help="postgres DSN with CREATE DATABASE rights (--self-test)")
    ap.add_argument("--dsn", help="DSN of the database to inspect (--report)")
    ap.add_argument("--db-name", default="verify_0015_merge", help="scratch DB name (--self-test)")
    args = ap.parse_args()

    if args.self_test:
        if not args.admin_dsn:
            ap.error("--self-test requires --admin-dsn")
        return self_test(args.admin_dsn, args.db_name)
    if not args.dsn:
        ap.error("--report requires --dsn")
    return report(args.dsn)


if __name__ == "__main__":
    sys.exit(main())
