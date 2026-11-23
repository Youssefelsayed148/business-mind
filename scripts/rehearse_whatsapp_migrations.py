"""Companion to the PowerShell wrapper; runs only on a fresh wa_rehearsal_* DB.

The wrapper creates/restores/drops the DB. Credentials stay inside the backend.
No production snapshot is needed for the default synthetic-volume rehearsal.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-name', required=True)
    parser.add_argument('--backend-dir', type=Path, default=Path(__file__).resolve().parents[1] / 'backend')
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--snapshot-restored', action='store_true')
    parser.add_argument('--lead-rows', type=int, default=100000)
    parser.add_argument('--messages-per-lead', type=int, default=3)
    args = parser.parse_args()
    if not re.fullmatch(r'wa_rehearsal_[0-9a-f]{32}', args.database_name):
        parser.error('Only a generated wa_rehearsal_<uuid> database is allowed')
    if args.lead_rows < 100 or args.messages_per_lead < 1:
        parser.error('Use at least 100 leads and one message per lead')
    # The repository's alembic/ package must not shadow the installed CLI library.
    sys.path = [p for p in sys.path if Path(p or '.').resolve() != args.backend_dir.resolve()]
    from alembic import command
    from alembic.config import Config
    sys.path.append(str(args.backend_dir))
    from sqlalchemy import create_engine, event, inspect, text
    from sqlalchemy.engine import Engine, make_url
    from app.core.config import settings

    settings.DATABASE_URL = make_url(settings.DATABASE_URL).set(database=args.database_name).render_as_string(hide_password=False)
    engine = create_engine(settings.DATABASE_URL, hide_parameters=True)
    config = Config(str(args.backend_dir / 'alembic.ini'))
    config.set_main_option('script_location', str(args.backend_dir / 'alembic'))
    statements, timings = [], []
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'database': args.database_name,
              'source': 'supplied snapshot' if args.snapshot_restored else 'synthetic',
              'postgres_version': None, 'steps': timings, 'statements': statements, 'passed': False}

    @event.listens_for(Engine, 'before_cursor_execute')
    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        normalized = ' '.join(statement.split())
        if normalized.upper().startswith(('ALTER ', 'CREATE INDEX', 'CREATE UNIQUE INDEX', 'UPDATE WHATSAPP_', 'DELETE FROM WHATSAPP_', 'DROP TABLE')):
            statements.append(normalized)

    def migrate(operation, revision):
        started = time.monotonic()
        getattr(command, operation)(config, revision)
        timings.append({'operation': operation, 'target': revision, 'seconds': round(time.monotonic() - started, 3)})

    def revision():
        with engine.connect() as conn:
            return conn.execute(text('SELECT version_num FROM alembic_version')).scalar_one()

    def existing_state():
        with engine.connect() as conn:
            tables = inspect(conn).get_table_names()
            counts = {table: conn.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one()
                      for table in tables if table != 'alembic_version'}
            constraints = dict(conn.execute(text("""
                SELECT c.conrelid::regclass::text || ':' || c.conname, pg_get_constraintdef(c.oid)
                FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace
                WHERE n.nspname = 'public'
            """)).all())
            columns = {table: {c['name']: {'nullable': c['nullable'], 'type': str(c['type']), 'default': c['default']}
                               for c in inspect(conn).get_columns(table)} for table in counts}
            return {'row_counts': counts, 'constraints': constraints, 'columns': columns}

    def assert_preserved(before, after, *, head):
        for table, count in before['row_counts'].items():
            assert after['row_counts'][table] == count, f'Existing row count changed: {table}'
        for key, definition in before['constraints'].items():
            assert after['constraints'].get(key) == definition, f'Existing constraint changed: {key}'
        for table, columns in before['columns'].items():
            for name, definition in columns.items():
                expected = {**definition, 'nullable': True} if head and table == 'messages' and name == 'lead_id' else definition
                assert after['columns'][table][name] == expected, f'Existing column changed: {table}.{name}'

    def prepare_synthetic():
        assert not inspect(engine).get_table_names(), 'Synthetic target must be empty'
        migrate('upgrade', '0017_workspace_membership')
        # 0001 imports current metadata. Remove only the future outreach shape
        # to reproduce 0017 faithfully; do not stamp a head-shaped database.
        with engine.begin() as conn:
            for column in ('whatsapp_campaign_id', 'whatsapp_template_id', 'delivered_at', 'read_at'):
                conn.execute(text(f'ALTER TABLE messages DROP COLUMN IF EXISTS "{column}" CASCADE'))
            for column in ('quality_rating', 'messaging_limit_tier', 'outreach_paused', 'outreach_paused_reason',
                           'health_checked_at', 'ctwa_counts_as_consent', 'transactional_utility_attested',
                           'opt_out_keywords', 'opt_in_keywords', 'outreach_daily_cap', 'opt_in_link_salt', 'outreach_paused_at'):
                conn.execute(text(f'ALTER TABLE whatsapp_accounts DROP COLUMN IF EXISTS "{column}" CASCADE'))
            for table in ('whatsapp_campaign_recipients', 'whatsapp_campaigns', 'whatsapp_templates',
                          'whatsapp_consent_events', 'whatsapp_contacts'):
                conn.execute(text(f'DROP TABLE IF EXISTS "{table}"'))
            conn.execute(text('ALTER TABLE messages ALTER COLUMN lead_id SET NOT NULL'))
            conn.execute(text("INSERT INTO workspaces (id,name,slug) VALUES (gen_random_uuid(),'Migration volume','migration-volume')"))
            conn.execute(text("""
                INSERT INTO whatsapp_accounts (id,workspace_id,phone_number_id,status,business_vertical,
                    ai_enabled,ai_daily_message_cap,ai_handoff_after_turns,ai_messages_sent_today)
                SELECT gen_random_uuid(),w.id,'synthetic-' || g,'connected','general',false,100,8,0
                FROM workspaces w CROSS JOIN generate_series(1,100) g WHERE w.slug='migration-volume'
            """))
            conn.execute(text("""
                INSERT INTO leads (id,workspace_id,platform,whatsapp_account_id,ig_user_id,ig_username,
                                   lead_source,status,created_at,last_seen_at)
                SELECT gen_random_uuid(),a.workspace_id,'whatsapp',a.id,
                       '1555' || lpad(g::text,8,'0'),'Synthetic ' || g,'cold_dm','new',
                       now() - (g % 90) * interval '1 day', now() - (g % 7) * interval '1 day'
                FROM generate_series(1,:rows) g JOIN whatsapp_accounts a
                  ON a.phone_number_id = 'synthetic-' || (1 + g % 100)
            """), {'rows': args.lead_rows})
            conn.execute(text("""
                INSERT INTO messages (id,lead_id,direction,message_type,status,created_at,retryable,retry_count)
                SELECT gen_random_uuid(),l.id,'outbound','ai_reply','sent',l.created_at,false,0
                FROM leads l CROSS JOIN generate_series(1,:messages) g
            """), {'messages': args.messages_per_lead})
        statements.clear()  # Report only the requested 0018–0022 migration work.

    def head_checks():
        inspector = inspect(engine)
        required = {
            'whatsapp_contacts': {'uq_whatsapp_contacts_account_wa_id', 'ck_whatsapp_contacts_wa_id', 'ck_whatsapp_contacts_marketing_consent'},
            'whatsapp_accounts': {'ck_whatsapp_accounts_outreach_daily_cap', 'ck_whatsapp_accounts_opt_in_keywords_array'},
            'whatsapp_campaign_recipients': {'uq_whatsapp_campaign_recipients_campaign_contact', 'ck_whatsapp_campaign_recipients_status'},
            'messages': {'fk_messages_whatsapp_campaign_id', 'fk_messages_whatsapp_template_id'},
            'whatsapp_consent_events': {'ck_whatsapp_consent_events_event_type'},
        }
        for table, names in required.items():
            found = {c['name'] for c in inspector.get_check_constraints(table) + inspector.get_unique_constraints(table) + inspector.get_foreign_keys(table)}
            assert names <= found, (table, names - found)
        assert {'ix_whatsapp_contacts_workspace_consent'} <= {i['name'] for i in inspector.get_indexes('whatsapp_contacts')}
        assert {'ix_whatsapp_campaign_recipients_campaign_status'} <= {i['name'] for i in inspector.get_indexes('whatsapp_campaign_recipients')}
        with engine.connect() as conn:
            invalid = conn.execute(text("SELECT count(*) FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname='public' AND NOT c.convalidated")).scalar_one()
            assert invalid == 0, 'Unvalidated constraints remain'
            contacts = conn.execute(text('SELECT count(*) FROM whatsapp_contacts')).scalar_one()
            if not args.snapshot_restored:
                assert contacts == args.lead_rows
                assert conn.execute(text("SELECT count(*) FROM whatsapp_contacts WHERE marketing_consent <> 'unknown'")).scalar_one() == 0
            assert conn.execute(text('SELECT count(*) FROM whatsapp_accounts WHERE opt_in_link_salt IS NULL')).scalar_one() == 0
            assert 'completed_at' in {c['name'] for c in inspector.get_columns('whatsapp_campaigns')}
            # Exercise enforcement, rather than just trusting constraint names.
            for statement in ("UPDATE whatsapp_accounts SET outreach_daily_cap=0",
                              "UPDATE whatsapp_contacts SET wa_id='invalid'",
                              "UPDATE whatsapp_contacts SET marketing_consent='invalid'"):
                table = statement.split()[1]
                if conn.execute(text(f'SELECT count(*) FROM {table}')).scalar_one() == 0:
                    report.setdefault('constraint_probes', []).append({'statement': statement, 'result': 'empty table; catalog checked only'})
                    continue
                savepoint = conn.begin_nested()
                try:
                    conn.execute(text(statement))
                except Exception as exc:
                    assert getattr(getattr(exc, 'orig', None), 'sqlstate', None) == '23514', type(exc).__name__
                    report.setdefault('constraint_probes', []).append({'statement': statement, 'result': 'rejected: 23514'})
                else:
                    raise AssertionError('Constraint probe unexpectedly succeeded')
                finally:
                    savepoint.rollback()
            return contacts

    try:
        with engine.connect() as conn:
            report['postgres_version'] = conn.execute(text('SHOW server_version')).scalar_one()
        if not args.snapshot_restored:
            prepare_synthetic()
        assert revision() == '0017_workspace_membership', 'Snapshot must be at pre-0018 revision 0017'
        before = existing_state()
        report['before'] = before
        migrate('upgrade', 'head')
        assert revision() == '0022_whatsapp_opt_in'
        after = existing_state()
        assert_preserved(before, after, head=True)
        report['first_upgrade_contacts'] = head_checks()
        report['after_first_upgrade'] = after
        for expected in ('0021_whatsapp_campaign_done', '0020_whatsapp_outreach_services',
                         '0019_whatsapp_outreach_settings', '0018_whatsapp_outreach', '0017_workspace_membership'):
            migrate('downgrade', '-1')
            assert revision() == expected
            with engine.connect() as conn:
                for table, count in before['row_counts'].items():
                    assert conn.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one() == count
        assert_preserved(before, existing_state(), head=False)
        migrate('upgrade', 'head')
        assert revision() == '0022_whatsapp_opt_in'
        assert_preserved(before, existing_state(), head=True)
        report['second_upgrade_contacts'] = head_checks()
        report['passed'] = True
        print(f"Rehearsed 0017 -> 0022 -> 0017 -> 0022; leads={before['row_counts']['leads']}, messages={before['row_counts']['messages']}")
    finally:
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        args.report.write_text(json.dumps(report, indent=2), encoding='utf-8')
        engine.dispose()


if __name__ == '__main__':
    main()
