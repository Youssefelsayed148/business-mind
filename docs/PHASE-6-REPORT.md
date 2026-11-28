# Phase 6 report (TEMPLATE)

Status: **EMPTY TEMPLATE. No cell below has a result yet.** Written 2026-11-28 for `docs/PHASE-6-PLAN.md`. Each result cell is filled only from a command or document that produced it (rule 6 in `CLAUDE.md`: never invent results). Owner-run steps are filled from the output the owner sends back. "NOT RUN" is a valid entry and must say why.

Header (fill in at the end): staging commit ______; Many head ______; SaaS head ______; report date (UTC) ______; author of each section ______.

## 1. Step results

Result values: PASS, FAIL, BLOCKED, NOT RUN. Evidence is a file path, a command with its output, or a link to a run record.

| Step | What | Who runs | Date (UTC) | Result | Evidence | Notes / open items |
|---|---|---|---|---|---|---|
| 6.0 | Readiness: gates A1 to A9, restored-copy link check (B), decisions C (`docs/PHASE-6-0-READINESS.md`) | Owner | | | | |
| 6A | Edge and internal TLS: overlay passes `docker compose config`; TLS checks scripted; allowlist tests pass with HTTPS (`docs/staging/6A-*`) | Claude writes, owner decides | | | | |
| 6B | Staging stack: stack healthy; edge deny checks pass from outside (`docs/staging/6B-*`) | Owner deploys | | | | |
| 6C | Backup and restore drill: restored on a clean machine; row counts and Alembic heads match (`docs/staging/6C-backup-restore-drill.md`) | Owner | | | | |
| 6D | Alerts: a deliberate failure raises one alert (`docs/staging/6D-alerts.md`) | Owner | | | | |
| 6E | End-to-end on the Meta test number: written results per channel; failures triaged (`docs/staging/6E-e2e-test-number.md`) | Owner | | | | |
| 6F | Load check: numbers recorded against stated targets (`docs/staging/6F-load-check.md`; targets pending decision D3) | Owner | | | | |
| 6G | Security review: no open critical finding; every open item has an owner and a date | Claude reviews, owner reads | | | | |
| 6H | Soak and report: one week of test traffic, daily notes (section 4) | Owner | | | | |

### 1.1 Detail per step (copy the step's own result template here, or link it)

| Step | Key numbers or answers | Result |
|---|---|---|
| 6.0 | A1 to A9 results; link check counts and elapsed time | |
| 6A | TLS checks run; certificates and renewal path | |
| 6B | Services healthy; edge deny checks; secrets rotation procedure written | |
| 6C | Backup size, copy time, restore times for many and saas, tables compared, mismatches, Alembic heads (source / restored / repo) | |
| 6D | Test mail received; closed-port alert; stop/start alert and recovery mail; thresholds in use | |
| 6E | Cases passed / failed / blocked per channel (WhatsApp W1 to W11, Facebook F1 to F8, Instagram I1 to I8, cross-cutting X1 to X4) | |
| 6F | Webhook burst summary; SaaS p50/p95/p99, error rate, requests/s; targets met or not | |
| 6G | Findings count by severity; dependency scan; Next upgrade PR | |
| 6H | Days completed; incidents; alerts raised | |

## 2. Exit criteria (copied from `docs/MERGE-PLAN.md`, Phase 6)

Work: staging on its own server and database with the Meta test number; end-to-end tests for WhatsApp, Facebook and Instagram on the test number; load check; the open SaaS items: backup/restore drill, alert receiver, security review; a one-week soak with test traffic.

| Exit criterion | Met? (yes / no / partly) | Evidence | Owner sign-off (name, date) |
|---|---|---|---|
| Written test report (this document, complete) | | | |
| No open critical findings (section 3) | | | |
| Backup restored successfully on a clean machine (6C) | | | |

Plan-level exit (`docs/PHASE-6-PLAN.md`): staging on its own server and database; Meta test number used; end-to-end for all three channels; load check done; alert receiver tested; security review done; one-week soak finished.

| Plan item | Done? | Evidence |
|---|---|---|
| Staging on its own server and database | | |
| End-to-end WhatsApp | | |
| End-to-end Facebook | | |
| End-to-end Instagram (code exercised, not edited; frozen check clean) | | |
| Load check | | |
| Backup/restore drill | | |
| Alert receiver and deliberate alert | | |
| Security review (6G) | | |
| One-week soak (6H) | | |

## 3. Open findings

Severity: critical, high, medium, low. Every open item needs an owner and a due date. Phase 3 review items 1 to 10 (`docs/PHASE-5-PLAN.md` section 6) go in here from 6G; none of the identity or data flags is enabled in staging until each is fixed or accepted in writing.

| ID | Source (step, case id, review item) | Description (sanitized) | Severity | Status (open / fixed / accepted) | Owner | Due | Fix or acceptance reference |
|---|---|---|---|---|---|---|---|
| | | | | | | | |
| | | | | | | | |
| | | | | | | | |

UNVERIFIED items carried from the checklists (list each with the step that should close it):

| Item | Step | Closed by | Result |
|---|---|---|---|
| | | | |

## 4. Soak daily log (6H: one week)

Traffic: scripted test traffic plus manual daily test messages on the Meta test number (decision D7). Fill one row per day from that day's health notes. Do not copy phone numbers, message text or secrets.

| Day | Date (UTC) | Health URLs ok | Alerts raised (count, why) | Backup made and age ok | Disk used % | Test messages sent / answered | Errors in logs (sanitized) | Notes | Initials |
|---|---|---|---|---|---|---|---|---|---|
| 1 | | | | | | | | | |
| 2 | | | | | | | | | |
| 3 | | | | | | | | | |
| 4 | | | | | | | | | |
| 5 | | | | | | | | | |
| 6 | | | | | | | | | |
| 7 | | | | | | | | | |

Soak summary: days completed ______; unplanned restarts ______; alerts raised ______; incidents and their finding ids ______.

## 5. Decisions and changes during Phase 6

| Date | Decision or change | Who | Reference |
|---|---|---|---|
| | | | |

## 6. Sign-off

| Role | Name | Date | Statement |
|---|---|---|---|
| Owner | | | Phase 6 accepted / accepted with listed open items / not accepted |
| Claude Code | | | Report assembled from the evidence above; no result invented |
