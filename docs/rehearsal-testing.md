# Rehearsal Testing Guide

Complete runbook for spinning up a clean environment, seeding demo data, and validating all major features of ManyOsirisChat.

---

## 1. Fresh Reset

Run these commands in order from the project root:

```powershell
# Tear down all containers and wipe volumes (database, redis)
docker compose down -v

# Rebuild images and start all services
docker compose up -d --build

# Run database migrations
docker compose exec backend alembic upgrade head

# Seed rehearsal data (users, accounts, campaigns, leads, messages, logs)
docker compose exec backend python -m app.scripts.seed_rehearsal
```

Expected output from the seed command:
```
Seeding rehearsal data (APP_ENV=development) …
  Workspace:          exists  (default)
  Users:              created=4  skipped=0
  Instagram accounts: created=10  updated=0
  Campaigns:          created=50  updated=0
  Comments:           created=15
  Leads:              created=15
  Messages:           created=~22
  Automation logs:    created=15
  Audit logs:         created=6

Rehearsal seed complete.
```

> **Idempotency**: Running the seed command a second time will skip already-existing users, accounts, campaigns, leads, messages, and comments. Counters will show `skipped=N` or `updated=N` instead of `created=N`.

---

## 2. Backup the Clean Seeded State

Before running any webhook load tests, save a clean snapshot:

```powershell
.\scripts\backup_postgres.ps1
```

This lets you restore to the clean seeded state at any point:

```powershell
.\scripts\restore_postgres.ps1
```

---

## 3. Webhook Batch Tests

Run from the project root (not inside Docker — the script reads `.env` directly):

```powershell
# 100 events, cycling through all keywords
python scripts\send_rehearsal_webhooks.py --count 100

# 300 events, all with keyword "prompt"
python scripts\send_rehearsal_webhooks.py --count 300 --keyword prompt

# 100 events, mixed keywords (random from full pool each request)
python scripts\send_rehearsal_webhooks.py --count 100 --mode mixed

# Verbose mode (one line per request)
python scripts\send_rehearsal_webhooks.py --count 20 --verbose

# Custom backend URL
python scripts\send_rehearsal_webhooks.py --count 100 --url http://localhost:8000/webhooks/meta
```

### Summary output

```
==================================================
  Total sent:          100
  Success (200):        97
  Failed (non-200):      1
  Rate limited (429):    2
  Avg response time:   43.2 ms
==================================================
```

### Progress indicators (non-verbose)
- `.` = 200 OK
- `R` = 429 rate limited
- `E` = connection error
- `[4xx]` / `[5xx]` = HTTP error with code

---

## 4. Automated Lifecycle Check

After seeding, verify the full campaign lifecycle via the API:

```powershell
python scripts\rehearsal_lifecycle_check.py
```

This logs in as `owner@osiris.com` and:
1. Lists all campaigns (shows rehearsal count by status)
2. Activates one paused campaign
3. Pauses one active campaign
4. Archives one active campaign
5. Unarchives the just-archived campaign
6. Fetches audit logs and dashboard overview

Expected output:
```
Connecting to http://localhost:8000 as owner@osiris.com …
  Login: OK

── Campaign list ──────────────────────────────────
  ✓  Listed campaigns: 50 total, 50 rehearsal
  ✓  Rehearsal statuses: active=35  paused=10  archived=5

── Activate paused campaign ───────────────────────
  ✓  Activated '[Rehearsal] Discount Drop – Paused'  — status → active

── Pause active campaign ──────────────────────────
  ✓  Paused '[Rehearsal] Price Check'  — status → paused

── Archive active campaign ────────────────────────
  ✓  Archived '[Rehearsal] Demo Request'  — status → archived

── Unarchive campaign ─────────────────────────────
  ✓  Unarchived '[Rehearsal] Demo Request'  — status → paused

── Audit / automation logs ────────────────────────
  ✓  Audit logs (/dashboard/logs)  — 6 records

====================================================
  Lifecycle check PASSED — all steps completed.
====================================================
```

---

## 5. Manual Browser Checks

### Login matrix

| URL           | Email                  | Password   | Role     | Expected access |
|---------------|------------------------|------------|----------|-----------------|
| `/login`      | `owner@osiris.com`     | `password` | Owner    | Full access     |
| `/login`      | `admin2@osiris.com`    | `password` | Admin    | Full access     |
| `/login`      | `operator@osiris.com`  | `password` | Operator | Manage campaigns, no user admin |
| `/login`      | `viewer@osiris.com`    | `password` | Viewer   | Read-only       |

### Role permission checks

| Action                         | Owner | Admin | Operator | Viewer |
|-------------------------------|-------|-------|----------|--------|
| View campaigns list           | ✓     | ✓     | ✓        | ✓      |
| Create / edit campaign        | ✓     | ✓     | ✓        | ✗      |
| Activate / pause / archive    | ✓     | ✓     | ✓        | ✗      |
| Delete campaign               | ✓     | ✓     | ✗        | ✗      |
| View leads / messages / logs  | ✓     | ✓     | ✓        | ✓      |

### Campaigns page

- [ ] Filter by **status**: active / paused / archived / all
- [ ] Filter by **delivery mode**: instant / follow_prompt
- [ ] Search by campaign name
- [ ] Counters (`total_triggers`, `successful_sends`, `failed_sends`) are populated
- [ ] Keywords are shown per campaign

### Campaign lifecycle (UI)

1. Find a **paused** rehearsal campaign → click **Activate** → confirm status changes to `active`
2. Find an **active** campaign → click **Pause** → confirm `paused`
3. Find an **active** campaign → click **Archive** → confirm `archived`
4. Find an **archived** campaign → click **Unarchive** → confirm returns to `paused`

### Instant delivery flow

1. Send a webhook for keyword that matches an active `instant` campaign:
   ```powershell
   python scripts\send_rehearsal_webhooks.py --count 1 --keyword price
   ```
2. Open the **Messages** page → verify a new `sent` or `queued` message appears within seconds
3. Open the **Leads** page → confirm the commenter was captured as a lead

### Follow-prompt delivery flow

1. Send a webhook matching an active `follow_prompt` campaign:
   ```powershell
   python scripts\send_rehearsal_webhooks.py --count 1 --keyword prompt
   ```
2. In **Messages**, verify a `follow_prompt` type message appears with status `sent`
3. After ~10 seconds, verify a `final_delivery` message appears for the same lead
4. In **Campaigns**, confirm `successful_sends` incremented

### Leads page

- [ ] Lead rows show `ig_username`, `source campaign`, triggered keyword (from comment)
- [ ] `last_seen_at` is populated
- [ ] Source comment ID is linked where available

### Messages page

- [ ] `status` column shows mix of `sent`, `failed`, `queued`
- [ ] `message_type` shows `final_delivery` and `follow_prompt`
- [ ] Failed messages show `error_code` and `error_message`
- [ ] `retry_count` > 0 for some failed rows

### Logs / Audit page

- [ ] `actor_email` shown as `owner@osiris.com` for seed actions
- [ ] Actions include: `campaign_activated`, `campaign_paused`, `campaign_archived`, `login_success`
- [ ] Severity levels: `info`, `warning`, `danger`

### Rate limit behavior

```powershell
# Fire 50 rapid requests — expect some 429s
python scripts\send_rehearsal_webhooks.py --count 50 --verbose
```

- [ ] Some requests return **429** (visible in terminal output as `R`)
- [ ] 429 responses do not crash the backend
- [ ] After brief pause, new requests succeed again

### Error handling (backend down)

1. Stop the backend container: `docker compose stop backend`
2. Send a webhook: `python scripts\send_rehearsal_webhooks.py --count 5`
3. Verify output shows `E` (connection error), not a Python crash
4. Restart backend: `docker compose start backend`
5. Verify backend recovers and serves requests normally

---

## 6. Duplicate Webhook Protection Test

Verify that sending the same comment event multiple times creates only one lead, one message, and one campaign trigger — not duplicates.

### Using a fixed comment ID

```powershell
# Send the same comment_id 5 times — only the first should be processed
python scripts\send_rehearsal_webhooks.py --duplicate-comment-id rehearsal_dup_test_001 --count 5 --keyword demo
```

### Using the auto-generated repeat shorthand

```powershell
# Auto-generates a comment_id then sends it 5 times
python scripts\send_rehearsal_webhooks.py --repeat-same-event 5 --keyword price
```

### Expected result

```
Duplicate test  comment_id: rehearsal_dup_test_001
Total sent:          5
Success (200):       5  (all should be 200)
Failed (non-200):    0
Rate limited (429):  0
Expected result:     only 1 lead/message created (first event processed)
```

All 5 requests return **200** (Meta expects 200 for every received webhook, even duplicates).  
After checking the **Leads** and **Messages** pages, only **1 lead** and **1 message** should appear for `rehearsal_dup_test_001`.

The `processed_webhook_events` table records the first delivery. Subsequent identical `comment_id`s hit the unique constraint and are silently skipped before creating any leads, messages, or automation logs.

### Verify in database (optional)

```bash
docker compose exec postgres psql -U postgres -d instagram_automation \
  -c "SELECT event_key, received_at FROM processed_webhook_events WHERE event_key LIKE '%rehearsal_dup%';"
```

Expected: exactly **1 row** for the comment ID.

---

## 7. Duplicate Webhook Protection Notes

**How it works:**

1. Each incoming `comment_id` is hashed into a stable `event_key` (`ig_comment:<comment_id>`).
2. Before processing the comment, a row is inserted into `processed_webhook_events` with a `UNIQUE (provider, event_key)` constraint.
3. If the row already exists (duplicate delivery), the insert fails with an `IntegrityError`, the change is silently skipped, and no lead/message/log is created.
4. The overall webhook response is still **200** — Meta sees success and stops retrying.

**Cleanup:** The `processed_webhook_events` table can be safely pruned of rows older than 30–90 days. The long-term idempotency is covered by the `comments` table unique constraint on `comment_id`.

```sql
-- Prune rows older than 60 days (safe to run on a schedule)
DELETE FROM processed_webhook_events WHERE received_at < NOW() - INTERVAL '60 days';
```

---

## 8. Post-Populated Backup

After filling the database with webhook data, save a populated snapshot:

```powershell
.\scripts\backup_postgres.ps1
```

Label it differently from the clean snapshot (the script appends a timestamp automatically).

---

## 9. Seeded Users Reference

| Email                   | Password   | Role     |
|-------------------------|------------|----------|
| `owner@osiris.com`      | `password` | owner    |
| `admin2@osiris.com`     | `password` | admin    |
| `operator@osiris.com`   | `password` | operator |
| `viewer@osiris.com`     | `password` | viewer   |

---

## 10. Seeded Data Summary

| Entity              | Count  | Notes                                      |
|---------------------|--------|--------------------------------------------|
| Users               | 4      | owner, admin, operator, viewer             |
| Instagram accounts  | 10     | osiris_demo_01 … osiris_demo_10, connected |
| Campaigns           | 50     | mix of active/paused/archived, instant + follow_prompt |
| Keywords            | ~70    | price, demo, offer, guide, prompt, discount, start, info, course, book |
| Comments            | 15     | realistic keyword-triggered comments       |
| Leads               | 15     | unique per account+user                    |
| Messages            | ~22    | mix of sent/failed, final_delivery + follow_prompt |
| Automation logs     | 15     | one per comment event                      |
| Audit logs          | 6      | actor=owner@osiris.com                     |

All rehearsal campaigns are prefixed with `[Rehearsal]` to distinguish them from any real data.

---

## 11. Production Safety

The seed script checks `APP_ENV` before running:

```
ERROR: Refusing to seed in production mode.
       Pass --force to override (use with caution).
```

To override (with full awareness of consequences):

```bash
docker compose exec backend python -m app.scripts.seed_rehearsal --force
```

---

## 12. Quick Reference Commands

```powershell
# Full fresh reset
docker compose down -v && docker compose up -d --build
docker compose exec backend alembic upgrade head
docker compose exec backend python -m app.scripts.seed_rehearsal

# Backup clean state
.\scripts\backup_postgres.ps1

# Run webhook load tests
python scripts\send_rehearsal_webhooks.py --count 100 --mode mixed
python scripts\send_rehearsal_webhooks.py --count 300 --keyword prompt

# Lifecycle check
python scripts\rehearsal_lifecycle_check.py

# Duplicate webhook protection test
python scripts\send_rehearsal_webhooks.py --repeat-same-event 5 --keyword demo
python scripts\send_rehearsal_webhooks.py --duplicate-comment-id my_comment_001 --count 5

# Backend logs
docker compose logs -f backend

# Worker logs
docker compose logs -f worker
```
