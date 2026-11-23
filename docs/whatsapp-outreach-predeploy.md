# WhatsApp outreach pre-deploy checklist

Keep outreach disabled until the snapshot rehearsal and the account checks below are complete. The Phase 7 [verification report](whatsapp-outreach-phase7-report.md) records what was actually run.

## Production configuration

| Variable | Initial production value / requirement |
| --- | --- |
| `APP_ENV` | `production` |
| `WHATSAPP_OUTREACH_ENABLED` | `false` in API, workers and beat initially |
| `META_MOCK_PRIVATE_REPLIES` | `false`; confirm all deployed processes use it |
| `DASHBOARD_BASE_URL` | Actual public HTTPS dashboard origin; no localhost or API origin |
| `WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID` | Configuration ID belonging to the production Meta app; verify allowed HTTPS domains and redirects |
| `WHATSAPP_RETRYABLE_META_CODES` | Empty string initially. Add a code only after documented safe retry semantics; `131048` and `131049` are always excluded |
| `WHATSAPP_BROKER_VISIBILITY_TIMEOUT_SECONDS` | `3600`; actual Redis/Celery visibility timeout must also be 3600 |
| `WHATSAPP_DISPATCH_MAX_BATCH_WINDOW_SECONDS` | `300`, strictly less than half the actual visibility timeout |
| `WHATSAPP_DISPATCH_BATCH_SIZE` | `20` initially |
| `WHATSAPP_HEALTH_STALE_MINUTES` | `60`; health poll runs every 15 minutes |
| `WHATSAPP_PUBLIC_OPT_IN_IP_LIMIT` / `WHATSAPP_PUBLIC_OPT_IN_ACCOUNT_LIMIT` | `10` / `100` per `3600` seconds initially |
| `WHATSAPP_TEST_SEND_DAILY_LIMIT` | `20` initially; use only 1–2 internal numbers for launch |
| `APP_SECRET_KEY`, `JWT_SECRET`, token encryption key, Meta app secret | Production secrets from the secret store; stable across API/worker replicas, never printed |
| `REDIS_URL`, `DATABASE_URL` | Production services; Redis must be reachable for public opt-in and outreach token/defer gates |
| `RATE_LIMIT_ENABLED` | `true`; the public opt-in limiter independently fails closed on Redis failure |

- [ ] Compare effective settings across API and workers; restart processes after env changes.
- [ ] Check `celery_app.conf.broker_transport_options` and the Redis transport's effective timeout. The WhatsApp timeout setting bounds dispatcher countdowns; it does **not** configure Celery transport options. Keep both at 3600 until explicitly configuring transport defaults.
- [ ] Confirm only one beat scheduler operates for this deployment.
- [ ] Confirm worker task registration includes `app.workers.whatsapp_tasks` and all four WhatsApp beat entries.
- [ ] Keep logs free of bearer headers, tokens and signed public URLs; redact signed opt-in paths in reverse-proxy access logs. Application consent evidence uses a placeholder path.

## Migration and deployment order

1. Obtain a fresh `pg_dump` at `0017_workspace_membership`, without `--create`. Retain the production backup outside the application tree.
2. Run `scripts/rehearse_whatsapp_migrations.ps1 -Snapshot <file>` for custom-format dumps, or add `-SnapshotFormat plain` for plain SQL. The wrapper creates a unique `wa_rehearsal_<uuid>` database, restores only there, executes the rehearsal, exports its JSON report, and drops the temporary DB. Use `-KeepDatabase` only for investigation. No snapshot is assumed to exist.
3. Review row counts, constraints, ALTER/index statements, migration timings, disk/WAL headroom and blockers. The default synthetic rehearsal seeds 100 accounts, 100,000 leads and 300,000 messages at the pre-0018 shape. It is not a production concurrency benchmark.
4. Stop API writes and workers/beat for a controlled maintenance window unless the safer migration forms below are separately implemented and rehearsed. Set bounded lock/statement timeouts appropriate to measured production volumes. Do not blindly retry a migration waiting behind a long transaction.
5. Apply migrations first: `alembic upgrade head`; confirm `0022_whatsapp_opt_in` and constraints/indexes.
6. Deploy the API with outreach disabled.
7. Deploy workers, then beat, with outreach disabled. Verify registration, Redis connectivity and health polling.
8. Deploy the dashboard and verify its public HTTPS opt-in origin.

## Lock-sensitive statements and safer forms

The emitted statements are recorded in [the rehearsal artifact](whatsapp-outreach-migration-rehearsal.json). PostgreSQL normally takes `ACCESS EXCLUSIVE` for ALTER TABLE; metadata-only operations still wait for locks. A volatile column default rewrites the table. [PostgreSQL ALTER TABLE documentation](https://www.postgresql.org/docs/15/sql-altertable.html).

| Revision | Current operation / live-table risk | Safer deployment form |
| --- | --- | --- |
| 0018 | Adds four columns and two FKs to shared `messages`, five columns and a CHECK to `whatsapp_accounts`. Column additions are metadata-only but take locks; validating FKs/CHECKs scans tables. Locks precede the contact backfill and remain until the upgrade transaction commits | Split short DDL from resumable backfill; add FK/CHECK constraints `NOT VALID`, then `VALIDATE CONSTRAINT` separately. Use a lock timeout and a quiet window for short ALTER statements |
| 0018 | Backfill normalizes/sorts WhatsApp leads and inserts contacts in one transaction; three ordinary indexes and unique constraints are built after population | Backfill in bounded batches with checkpoints. For an already populated/live outreach table, build indexes with `CREATE INDEX CONCURRENTLY` outside a transaction, then attach unique indexes with `ADD CONSTRAINT ... UNIQUE USING INDEX`. Ordinary index creation on a new offline table is acceptable |
| 0019 | Adds constant-default booleans/cap and JSON columns; CHECK creation scans accounts under locks | Constant defaults avoid a rewrite on PostgreSQL 11+, but lock acquisition remains. Add CHECKs `NOT VALID`, validate separately |
| 0020 | `ALTER TABLE messages ALTER COLUMN lead_id DROP NOT NULL`; replaces recipient/template/consent CHECKs; bulk `queued` → `pending` update | DROP NOT NULL is metadata-only but needs an ALTER lock. Expand CHECKs separately and validate later; backfill status in bounded batches if rows already exist |
| 0021 | Adds nullable `completed_at` to campaigns | Metadata-only; short ALTER lock with timeout |
| 0022 | **`ADD COLUMN opt_in_link_salt UUID DEFAULT gen_random_uuid() NOT NULL` rewrites all accounts and indexes**, replaces consent CHECK and updates paused accounts | **Not suitable for unrestricted live execution on a large account table.** Add nullable UUID without a default, set the default separately for future inserts, backfill UUIDs in batches, add/validate a temporary `CHECK (opt_in_link_salt IS NOT NULL)`, then SET NOT NULL and drop the temporary CHECK. New column default alone does not backfill existing rows |

Concurrent index creation cannot run in the ordinary transactional Alembic block. Use an explicit autocommit block or a separate operational migration, check for invalid indexes after interruption, and rehearse the exact amended sequence. [PostgreSQL CREATE INDEX documentation](https://www.postgresql.org/docs/15/sql-createindex.html).

## Smoke tests after deployment

- [ ] `/health` is healthy; migrations show the expected single head.
- [ ] Owner/admin can access contacts, templates, campaigns and health; member/operator/viewer gets 403; another workspace's resource IDs get 404.
- [ ] Generate a fresh public opt-in link. Submit an internal number anonymously: accepted, one `opt_in_unverified` event, consent still unknown, no outbound template.
- [ ] Send the configured keyword from that number: consent becomes opted_in. Send STOP: consent becomes opted_out. Replay the webhook: no duplicate event/send.
- [ ] A dry-run leaves all row counts unchanged and reports permanent skips separately from temporary blocks.
- [ ] With the feature disabled, pending recipients stay pending and no new outbound reservations appear. Watch broker depth for repeated deferrals.
- [ ] Confirm template sync and health poll update only the intended account; test tokens never appear in API responses/logs.
- [ ] Inspect the dashboard's campaign stats/completion timestamp and delivery/read updates from an actual internal send.

## First-day enablement

1. Keep all accounts except the test account `outreach_paused=true` through a controlled operational DB change. There is no per-account feature-enable API; the env flag is global. Stop concurrent campaign starts while preparing the allowlist.
2. Connect the test account through Embedded Signup, configure its opt-in keyword, set a cap of 1–2, create/approve the template and obtain auditable consent from the internal recipients.
3. Run a scoped health refresh (`POST /whatsapp/accounts/{id}/health-refresh`), wait for a successful poll, and confirm non-RED quality plus `health_checked_at` inside the 60-minute freshness window. A webhook health signal alone does not confirm recovery after a pause.
4. Set `WHATSAPP_OUTREACH_ENABLED=true` consistently in API/workers/beat and restart them, keeping all other accounts paused. Clear the test account's pause only through the health-confirmed audited resume flow for its paused campaign, or a reviewed operational change if it has no campaign yet.
5. Dry-run, send to 1–2 internal numbers, observe Meta receipt and recipient counters, then test STOP and pause/resume with a new health poll.
6. Monitor failure share, quality, daily-cap usage, pending/sending age, queue depth and `outcome_unknown`. Never manually redeliver an unknown outcome.
7. If anything diverges, disable the global flag and pause campaigns; preserve message reservations and consent evidence for investigation.

## Rollback by revision

Prefer rolling back application images while retaining the expanded schema and keeping outreach disabled. Drain/stop workers before a schema downgrade; restore a backup into a new database before any destructive recovery.

| Downgrade | Notes |
| --- | --- |
| 0022 → 0021 | Deletes all `opt_in_unverified` events, drops pause timestamps and salts. Existing signed links cannot be preserved through downgrade/re-upgrade. Export evidence before any approved downgrade |
| 0021 → 0020 | Drops `completed_at`; recorded completion times are lost |
| 0020 → 0019 | Converts resubscribe → opt_in, deleted templates → disabled, pending/sending → queued; then restores `messages.lead_id NOT NULL`. **Intentionally fails if any leadless outreach message exists.** Do not synthesize fake leads or delete reservations merely to force rollback. Keep 0020 or explicitly migrate affected data |
| 0019 → 0018 | Drops account consent/keyword/cap settings and CHECKs; export configuration first |
| 0018 → 0017 | Drops five outreach tables, message outreach references/delivery timestamps and account health/pause columns. Outreach data is lost; pre-existing leads/messages remain. Requires a backed-up, explicitly destructive recovery plan after rollout |

The synthetic rehearsal checks the complete downgrade chain before new outreach traffic exists. It does not prove that downgrades preserve production consent/campaign data created after enabling outreach.

## Meta-side readiness

- [ ] Production app owns the correct WhatsApp product, WABA and phone-number linkage. Configure and verify the HTTPS webhook callback and verify token; verify webhook signature validation.
- [ ] Subscribe the app to each onboarded WABA. Enable `messages` (inbound messages and delivery/read/failure statuses), `message_template_status_update`, and `phone_number_quality_update`; prove each reaches its implemented handler. Keep the periodic template sync/health poll as recovery paths.
- [ ] Configure Embedded Signup using the production config ID, allowed domains and redirect URIs; complete a real onboarding and server-side code exchange without exposing access tokens to the dashboard.
- [ ] Prepare App Review videos using the deployed product: Embedded Signup/account onboarding; template create/submit/sync; consent flow; sending an approved template from the dashboard and receiving it in native WhatsApp; inbound reply/status handling. Provide reviewer credentials and exact reproduction steps.
- [ ] Confirm advanced access for `whatsapp_business_management` and `whatsapp_business_messaging`, business verification and any currently required Tech Provider steps before onboarding external customer businesses. Confirm registered numbers, billing and approved templates in the actual Meta app dashboard.

Use Meta's [Embedded Signup overview](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/overview/), [App Review guidance](https://developers.facebook.com/documentation/business-messaging/whatsapp/solution-providers/app-review/), and [webhook overview](https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/overview/). These pages returned HTTP 429 during Phase 7 research; the current approval UI/requirements still need operator confirmation. No live Meta configuration or App Review submission was performed.
