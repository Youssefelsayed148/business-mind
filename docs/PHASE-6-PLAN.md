# Phases 6 to 9: plan for approval

Status: **PLAN ONLY, awaiting the owner's approval. Nothing here is built or run.** Written 2026-11-28 after PRs #11, #12 and #13 merged into `main` (Phase 5 built; its restored-copy check and WSL gates are still the owner's). Facts marked "read" come from files in this repository. Exit criteria are copied from `docs/MERGE-PLAN.md`.

## 1. What I cannot do from the cloud container

Phase 6 is mostly operational. This container has no Docker, no nginx, no second machine and no network to Meta. So the split is:

| Who | What |
|---|---|
| Claude (code and docs, this container) | Staging overlay and config, scripts, test suites, runbooks, report templates, fixes for anything found |
| Owner (WSL or the staging server) | Provision the staging server and database, DNS, TLS certificates, secrets, the Meta test number, run every live step, send me the outputs |

Every live step below needs the owner's explicit approval and uses throwaway or staging data only. Rules from `CLAUDE.md` stay: no live tokens in the repo, no secrets printed, Instagram receive/dispatch/send code frozen (stop and ask if a step needs an edit), reversible changes, draft PRs.

## 2. Phase 6: staging and hardening

Goal (MERGE-PLAN): staging on its own server and database with the Meta test number; end-to-end tests for WhatsApp, Facebook and Instagram; load check; backup/restore drill, alert receiver, security review; one-week soak.
Exit: written test report; no open critical findings; backup restored on a clean machine.

### Steps (one branch and one draft PR each; stop for review after each)

| Step | Content | Who | Done when |
|---|---|---|---|
| 6.0 Readiness | Close the carried-over gates: WSL gates for Phases 4 and 5, restored-copy link check (`docs/DATA-UNIFICATION.md` section 18), owner confirms the Phase 5 design changes | Owner runs, Claude records | Results recorded in the progress files |
| 6A Edge and internal TLS | Edge TLS (decide: load balancer or nginx server block), internal TLS with a private CA so the production HTTPS rule holds for `many-api` and `saas-api`, Many transport pinning design (needs owner approval), production overlay made deployable | Claude writes, owner decides | Overlay passes `docker compose config`; TLS checks scripted; allowlist tests pass with HTTPS |
| 6B Staging stack | Staging overlay, host-only secrets file layout, `.env.staging.example` (placeholders), deploy and rollback scripts, DNS and firewall checklist | Claude writes, owner provisions and deploys | Stack healthy on the staging server; edge deny checks pass from outside |
| 6C Backup and restore drill | Scripts for both databases (Many Postgres 15, SaaS Postgres 17 with pgvector), restore on a clean machine, timing, result template | Claude writes, owner runs | Backup restored on a clean machine; row counts and the Alembic heads match |
| 6D Alerts | Alert receiver choice and wiring (health, error rate, queue depth, disk, backup age), test alert fired on purpose | Claude writes, owner supplies the receiver | A deliberate failure raises one alert |
| 6E End-to-end on the Meta test number | Scripted cases for WhatsApp, Facebook, Instagram: inbound, bot answer, human reply, opt-out, erasure (Phase 5 flow), delegation on and off. Instagram code is exercised, never edited | Owner runs live, Claude supplies scripts and checklist | Written results per channel; failures triaged |
| 6F Load check | Webhook burst and dashboard load with the existing rehearsal tools (`docs/rehearsal-testing.md`), plus a SaaS API load script; named limits and rate-limit zones checked | Claude writes, owner runs | Numbers recorded against stated targets (see decision D3) |
| 6G Security review | Review the whole merged surface (SSO exchange, Many proxy, erasure, link table, edge deny), the open Phase 3 review items, secrets handling, dependency scan, Next 16.4.3 notice | Claude reviews, owner reads | No open critical finding; every open item has an owner and a date |
| 6H Soak and report | One week of test traffic, daily health notes, final report `docs/PHASE-6-REPORT.md` | Owner runs, Claude assembles | Exit criteria below |

Order: 6.0, 6A, 6B first (nothing else can start without a stack). 6C to 6G can run in any order once 6B is up. 6H last.

### Must be settled before any flag is enabled (from earlier reviews, read in `docs/PHASE-5-PLAN.md` section 6)
Phase 3 review items 1 to 7 and 8 to 10 (TOTP reuse race, agency grant with deleted locations, limited Admin retention, agency reply design, agency Admin export, invitation existence leak, pending Owner invitation replace). These go into 6G; none of the identity or data flags (`DATA_UNIFICATION_ENABLED` included) is enabled in staging until they are fixed or accepted in writing.

### Other items folded into Phase 6
Many started with `--proxy-headers --forwarded-allow-ips=<SaaS API address>` for the public opt-in call; CI paused (billing), so every gate stays local unless the owner restores Actions; old Meta token revoke and secret rotation are scheduled for Phase 8 but the rotation procedure is written in 6B; not ported yet: leads CSV export, Instagram MockConnect, location and agency screens, authenticator QR (owner decides which are needed before cutover, D5).

## 3. Phase 7: data rehearsal and cutover (outline, detailed plan after Phase 6)

Work: restore copies of both live databases into staging, run the merged migrations and user mapping, compare row counts, time the migration. Then cut over one channel at a time (WhatsApp, Facebook, Instagram last), each with a fresh backup, an announced window, the owner's explicit approval, the Meta webhook URL and DNS switch, health watch and a ready rollback.
Exit: each channel runs on the new platform for the agreed watch period with no regressions.
Claude's part: migration and mapping scripts, row-count comparison tool, cutover and rollback runbooks per channel, dry run on restored copies. The owner owns all live actions. Instagram stays untouched until its own cutover step.

## 4. Phase 8: stabilise and retire (outline)

Old apps stay deployed and idle for 2 to 4 weeks as rollback; then archive (not delete) the old repositories, remove old VPS stacks, keep backups, revoke the old Meta token, rotate secrets. Exit: old apps retired; the platform is the only live system. All steps are the owner's; Claude supplies the checklist and verifies nothing still points at the old hosts.

## 5. Phase 9 (optional, later decision): single backend

Only if still worth it after Phase 8. Needs its own plan and owner approval, especially for Instagram code. Not planned here.

## 6. Decisions for the owner (with my recommendations)

| # | Question | Recommendation |
|---|---|---|
| D1 | Edge TLS: load balancer in front, or nginx server block with certificates (for example Let's Encrypt)? | Nginx server block with certbot, same as the existing VPS guide. Fewer parts, matches `docs/deployment-vps.md`. |
| D2 | Internal TLS: private CA, or relax the production HTTPS rule for two internal service names? | Keep the rule (your 2026-11-24 decision). Private CA, certificates mounted into both services. |
| D3 | Load targets (webhooks per second, dashboard users)? | Start from today's real traffic times 3. Please send the current peak numbers; I will not invent them. |
| D4 | Alert receiver (email, Telegram, Slack)? | Email first (no new account needed); add a chat channel later. |
| D5 | Which not-ported features must exist before cutover (leads CSV export, MockConnect, location and agency screens, authenticator QR)? | Leads CSV export only. The rest wait until after Phase 8 (scope-creep rule in MERGE-PLAN). |
| D6 | Staging server: provider and size, separate Postgres 15 and 17 as in production? | Same versions as production, one small VPS, separate from live. You choose the provider. |
| D7 | Soak length and traffic source (one week of scripted test traffic, plus the Meta test number)? | As written in MERGE-PLAN: one week, scripted plus manual daily test messages. |
| D8 | Restore GitHub Actions (billing) so gates run on every PR? | Yes if affordable; otherwise keep local gates and run them in WSL before each merge. |
| D9 | Next 16.4.3 security notice: run `next upgrade` as its own PR with the full web gates? | Yes, as a separate small PR in 6G. |
| D10 | Is the public repository acceptable, or make it private (Phase 0 asked private)? | Make it private before staging holds any real configuration. |

## 7. Risks

- Staging passes but production differs (host, TLS, Postgres versions). Mitigation: same images, same versions, same overlay.
- A live step run without a backup. Mitigation: each runbook starts with a backup and a restore check.
- Meta test number behaves differently from production numbers (templates, quality rating). Mitigation: label results as test-number results; real numbers are tested at cutover with a rollback.
- Instagram code exercised live for the first time in this repository. Mitigation: only the end-to-end test, no edits; any failure stops and comes to you.
- Findings pile up late. Mitigation: security review (6G) runs before the soak, not after.

## 8. Change log

- 2026-11-28, Claude Code: plan written from MERGE-PLAN, DEPLOY-OUTLINE, the backup, monitoring and security docs and the Phase 5 leftovers table. No code, no tests.
