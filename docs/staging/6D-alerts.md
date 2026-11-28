# 6D: Alerts (e-mail first)

Status: **script and unit tests written; unit tests run (fakes only). No mail has been sent, no SMTP server and no staging host was used.** Decision D4 (approved as recommended): e-mail first, a chat channel later. Exit criterion (`docs/PHASE-6-PLAN.md`): a deliberate failure raises one alert.

## What exists

| File | Purpose |
|---|---|
| `scripts/ops/alert_check.py` | One pass of all configured checks; one mail per run; stdlib only. `--dry-run` prints the mail and sends nothing; `--test-alert` sends a deliberate test mail. |
| `scripts/ops/test_alert_check.py` | 23 unit tests with fake HTTP, fake SMTP, fake commands. |

Relation to `docs/monitoring.md`: that file lists the conditions to alert on and suggests an external uptime monitor and Sentry. This script covers health, backup age, disk and optional queue/Redis from the server itself. It does **not** cover: SSL expiry (`docs/monitoring.md` lists 14 days; use the external monitor or add later), Instagram token expiry, failed-message rate, "no webhook events". Those stay with `docs/monitoring.md` or later work.

## What is checked

A check runs only when its variable is set (disk always runs, default path `/`). Defaults are starting values; the owner changes them with the variables.

| Check | Variable | Default | Alerts when |
|---|---|---|---|
| Health URLs | `ALERT_HEALTH_URLS` (comma list) or `--health-url` | none | Not HTTP 200, no answer in 10 s, or the JSON body has a field with value `error` (Many `/health` reports `database` / `redis`) or `status` `not_ready` (SaaS `/ready`) |
| Backup age | `ALERT_BACKUP_DIR`, `ALERT_BACKUP_MAX_AGE_HOURS` | none, 26 | Newest entry in the directory is older than the limit, or the directory is missing/empty. Fits the daily `backup_all.sh --target DIR` |
| Disk | `ALERT_DISK_PATHS` (comma list), `ALERT_DISK_MAX_PERCENT` | `/`, 85 | Percent used above the limit |
| Redis | `ALERT_REDIS_CMD` | none | Command fails or output lacks `PONG`. Example: `docker compose -f docker-compose.unified.yml exec -T redis redis-cli ping` |
| Queue length | `ALERT_QUEUE_CMD`, `ALERT_QUEUE_MAX` | none, 500 | Last word of the output (an integer) is above the limit. Example: `docker compose -f docker-compose.unified.yml exec -T redis redis-cli llen celery`. **UNVERIFIED:** the Celery queue name(s) in use; check the worker config before choosing the key |
| Repeat control | `ALERT_STATE_FILE`, `ALERT_REPEAT_HOURS` | none, 6 | With a state file: the same failures are mailed again only after the repeat time; a "RECOVERED" mail follows when all is ok again. Without it: one mail every run while failing |

Commands run without a shell (split with `shlex`), as the user that runs the script; that user needs Docker access for the Docker examples.

Suggested health URLs (placeholders; use your real staging hosts): `https://MANY_HOST/health`, `https://SAAS_API_HOST/health`, and `https://SAAS_API_HOST/ready` if the edge exposes it (**UNVERIFIED** which of these paths the edge routes; check with 6A/6B). Do not put secrets or tokens in URLs: they are printed in the mail.

## Mail settings (environment variables)

| Variable | Meaning |
|---|---|
| `ALERT_SMTP_HOST`, `ALERT_SMTP_PORT` (587) | Owner-supplied relay |
| `ALERT_SMTP_STARTTLS` (1) | Set `0` only for a local relay |
| `ALERT_SMTP_USER`, `ALERT_SMTP_PASSWORD` | Optional login. Keep the password in the host-only env file (mode 600), never in git, never on the command line |
| `ALERT_MAIL_FROM`, `ALERT_MAIL_TO` (comma list) | Sender and recipients |
| `ALERT_SUBJECT_PREFIX` (`[business-mind]`) | Subject prefix |

Exit codes: 0 all ok, 1 a check is failing, 2 configuration or mail error (the script never prints the password; an SMTP error prints only the exception type).

## Setup on the staging host

1. Create `/etc/business-mind/alerts.env` (mode 600, owner root) with the variables above, placeholders replaced by your real values.
2. Dry run first: `set -a; . /etc/business-mind/alerts.env; set +a; python3 scripts/ops/alert_check.py --dry-run`. Read the printed mail.
3. Fire the test mail (below). Confirm it arrives (also check spam).
4. Install the schedule.

Cron example (every 5 minutes; the daily backup line is the owner's choice of time):

```cron
*/5 * * * * root set -a; . /etc/business-mind/alerts.env; set +a; /usr/bin/python3 /opt/business-mind/scripts/ops/alert_check.py >> /var/log/business-mind-alerts.log 2>&1
15 3 * * * root set -a; . /etc/business-mind/alerts.env; set +a; cd /opt/business-mind && ENV_FILE=/etc/business-mind/stack.env scripts/ops/backup_all.sh --target /var/backups/business-mind >> /var/log/business-mind-backup.log 2>&1
```

systemd timer example. File `/etc/systemd/system/bm-alerts.service`:

```ini
[Service]
Type=oneshot
EnvironmentFile=/etc/business-mind/alerts.env
ExecStart=/usr/bin/python3 /opt/business-mind/scripts/ops/alert_check.py
# exit 1 means "a check is failing"; keep the unit green so only the mail reports it
SuccessExitStatus=1
```

File `/etc/systemd/system/bm-alerts.timer`:

```ini
[Timer]
OnBootSec=2min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
```

Enable with `systemctl enable --now bm-alerts.timer`. **NOT RUN:** neither example has been tried; paths are placeholders.

Note: if the whole host or the network is down, this script cannot mail. Keep one external uptime monitor from `docs/monitoring.md` as the second line.

## Deliberate failure test (the exit criterion)

Do each on staging, with the real mail settings. Record what you see.

1. **Mail path only:** `python3 scripts/ops/alert_check.py --test-alert` should print `Mail sent: [business-mind] TEST alert from <host>` and one mail arrives.
2. **Health failure, no service touched:** `python3 scripts/ops/alert_check.py --health-url http://127.0.0.1:9/health` (port 9 is closed). Expect one `[FAIL]` line, one `ALERT` mail, exit code 1. Run it again with `ALERT_STATE_FILE=/tmp/bm-alert-test.json` set: the second run prints `Same failures already mailed recently; not mailing again.`
3. **Real service failure (staging only, owner approves):** stop one non-critical container (for example `docker compose ... stop saas-worker` if the queue check is set, or `stop many-api` if its health URL is set), wait for the next timer run, expect one alert, start it again, expect one `RECOVERED` mail on a later run (needs `ALERT_STATE_FILE`). Rollback: `docker compose ... start <service>`.
4. **Backup age and disk (no real damage):** run with `ALERT_BACKUP_MAX_AGE_HOURS=0.001` or `ALERT_DISK_MAX_PERCENT=1` for one manual run; expect the matching `[FAIL]` line.

| Test | Expected | Result (owner fills in) |
|---|---|---|
| 1 test mail | one mail, exit 0 | |
| 2 closed port | one ALERT mail, exit 1; repeat suppressed with state file | |
| 3 container stop and start | one ALERT, later one RECOVERED | |
| 4 low thresholds | FAIL lines for backup age / disk | |

## What I ran here

`python3 scripts/ops/test_alert_check.py` (23 tests, fakes only) and a `--dry-run` against a closed local port; see `docs/PHASE-6-REPORT.md` or the session report for the exact output. Real SMTP, cron, systemd and Docker commands: NOT RUN.
