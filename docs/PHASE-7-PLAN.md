# Phase 7 plan: data rehearsal and cutover

Status: **PLAN ONLY, awaiting the owner's approval. Nothing here is built or run.** Written 2026-11-28 after PR #16 (Phase 6 build) merged into `main`; Phase 6 is not closed (live runs and the soak are the owner's). Facts marked "read" come from files in this repository; "not known" means I have no evidence and need your answer. Exit criteria come from `docs/MERGE-PLAN.md`.

Goal (MERGE-PLAN): restore copies of both live databases into staging, run the merged migrations and the user mapping, compare row counts, time the migration. Then cut over one channel at a time (WhatsApp, Facebook, Instagram last), each with a fresh backup, a short announced window, the owner's explicit approval, the Meta webhook URL and DNS switch, a health watch and a ready rollback.
Exit: each channel runs on the new platform for the agreed watch period with no regressions.

## 1. What I cannot see and need from you (facts, not opinions)

I have never seen the live systems. The ground rules forbid touching them. Before a design can be final I need these, as plain answers or read-only command output (never a password or token):

| # | Fact | How to get it |
|---|---|---|
| F1 | Where Many and the SaaS run today (provider, one VPS or two, OS, Docker versions) | your notes |
| F2 | Live Alembic heads: Many (merged repo expects `0031_sso_link`) and SaaS (merged repo expects `0038_grant_location_scope`) | `alembic current` in each live container, read-only |
| F3 | Database sizes and top table row counts for both | `\l+` and a row-count query I will write (read-only) |
| F4 | Where uploaded files live on the SaaS (storage volume path and size) | `du -sh` on the volume |
| F5 | Which Meta products send webhooks to which URL today (WhatsApp, Messenger, Instagram) and whether each product has its own callback URL in the Meta app | Meta app dashboard, screenshot with secrets hidden |
| F6 | Which channels are delegated to the SaaS bot today, and which organizations exist | the SaaS and Many admin lists |
| F7 | Where the encryption keys live today (Many `TOKEN_ENCRYPTION_KEY`, SaaS `CHANNEL_SECRET_ENCRYPTION_KEYS`) and who can move them. They must come across unchanged or stored tokens become unreadable | a yes or no, never the value |
| F8 | Acceptable downtime per channel, and the quietest hours | your call |

## 2. The core design question: how does data move?

The merge plan says "restore copies into staging", but a cutover also has to decide what the new system uses as its data after the switch. Three options. I recommend deciding between A and B only after the rehearsal numbers exist.

| Option | How | For | Against |
|---|---|---|---|
| A. Expand in place | After a backup, apply the additive migrations to the live databases (Many `0031`, SaaS `0032` to `0038`; all additive, each with a downgrade, legacy columns kept per the identity design) and run the new code against them. Old and new Many can then run side by side on the same database. Channel cutover is only the webhook switch | No data copy, no divergence, rollback of a channel is a webhook switch back and loses no message | Writes a schema change to live databases. Both stacks must never run the same scheduled jobs twice (Celery beat, campaign dispatch); needs a job-ownership rule. Old code against the new schema is **not yet proven** (rehearsal step 7A.4) |
| B. Move to a new host | Fresh backup restored on the new host, migrated, verified; then switch. Channels still on the old system keep writing to the old database | Live databases never change until retired; clean rehearsal equals the real thing | Data written on the old side after the copy is missing on the new side. Needs a per-channel delta copy at each later cutover, and a reverse copy for a rollback. Largest risk of lost or duplicated messages |
| C. One window | Freeze, move everything except Instagram, switch | One copy, no delta | Violates "one channel at a time with a rollback"; large blast radius. **Not recommended** |

My lean: **A**, if rehearsal proves old code runs against the new schema and the job-ownership rule is simple. If it does not, **B** with a delta tool built and rehearsed first. The owner decides (Q1).

## 3. Steps (one branch and one draft PR each; stop for review after each)

| Step | Content | Who | Done when |
|---|---|---|---|
| 7.0 Facts and design | You answer F1 to F8. I write `docs/CUTOVER-DESIGN.md`: chosen option, data inventory (tables, files, secrets, Meta objects), job ownership, per-channel switch sequence, rollback ladder per channel, what is lost on rollback, communication drafts | You answer, I write | You approve the design |
| 7A Rehearsal tooling | `scripts/cutover/`: read-only inventory and row-count report for both databases, a before/after comparer, a timing log, a migration runner wrapper (backup check, advisory lock, dry run first), the old-code-against-new-schema test, a duplicate and orphan check (leads vs contacts, identities, tenant mapping), and the user migration steps already in `scripts/identity_migrate.py` (report, apply, map-report, map-apply, verify) wired in order. Fakes in tests; real runs are staging | I write | Tests pass on synthetic data; every step prints a result table |
| 7B Rehearsal on staging | You restore copies of both live databases and the file volume into staging (never the live ones), run 7A end to end, send me the output. I record counts, timings, differences and every anomaly in `docs/PHASE-7-REHEARSAL.md`. Repeat until two runs in a row give the same counts with no unexplained difference | You run, I record and fix | Counts match, timing known, user report reviewed, rehearsal record signed |
| 7C Cutover runbooks | One per channel: WhatsApp, Facebook, Instagram. Each lists: pre-checks, fresh backup and restore test, the announced window text (placeholders), exact Meta setting to change, DNS or proxy change, health watch commands and the thresholds that mean "roll back", the rollback steps in order, and the owner approval line to sign. Instagram's runbook only uses documented switches; no frozen code is edited, and if any step would need an edit I stop and ask | I write | You approve all three |
| 7D WhatsApp cutover | Window, switch, watch period (length set in Q4), decision | You run with me on call to read outputs; explicit approval before and after | Watch period passes with no regression |
| 7E Facebook cutover | Same | You run | Same |
| 7F Instagram cutover | Same; the last channel; frozen Instagram code unchanged (`check_instagram_frozen.py` on the deployed commit) | You run | Same |
| 7G Close | Report `docs/PHASE-7-REPORT.md`: per channel timeline, counts before and after, incidents, rollbacks, open items | I assemble | Exit criteria met |

Identity goes with the channels but separately: staff first, then one pilot organization, then the rest, by flag, as in `docs/IDENTITY-DESIGN.md` section 9. The Phase 3 and 6G open items must be fixed or accepted in writing before any identity flag is turned on live. Many's own login stays as the break-glass path.

## 4. What must be true before 7.0 can close

1. Phase 6 gates that touch Phase 7: backup restored on a clean machine (6C), staging stack healthy (6B), end-to-end cases passed on the Meta test number (6E).
2. The live heads (F2) are known and the migrations from those heads to the merged heads are chained and tested up, down, up on a copy.
3. Leads CSV export is ported (D5 recommended it before cutover).

## 5. Rollback principles (to be made exact in 7.0)

- Every window starts with a fresh backup of both databases and a restore test of it.
- The old stacks stay deployed and idle until Phase 8 (2 to 4 weeks).
- The Meta webhook switch is reversible in seconds; what is not reversible is data written on the new side. With option A that data is already in the shared database; with option B a reverse copy is needed or messages in the window are accepted as lost (owner decides, Q3).
- No channel is cut over while another channel's watch period is still open.
- A rollback is a decision for you, never automatic; the runbook gives the thresholds I recommend.

## 6. Risks

- **Lost or duplicated messages at the switch.** Meta retries failed webhooks for a while; the new side must accept events by id (idempotent). To be proven in the rehearsal with replayed webhooks.
- **Scheduled jobs running twice** (campaign dispatch, token refresh, health checks) when old and new stacks overlap. Needs one explicit owner of each job at every moment.
- **Encryption keys not carried across**: stored Meta tokens become unreadable. F7.
- **Instagram**: last, frozen code untouched, own rollback, test account first (Phase 0 policy).
- **Password and role migration** surprises: the migration tool reports per user and applies only a reviewed report (design section 7). Users who need a set-password link need a delivery path (D4, no email provider yet).
- **Live data in staging**: restored copies contain customer data. Staging then needs the same protection as production, and the copies are deleted after the rehearsal, with the deletion noted.
- **Timing**: the real window depends on the migration time measured in 7B; I will not promise a window before that number exists.

## 7. Decisions for the owner (with my recommendations)

| # | Question | Recommendation |
|---|---|---|
| Q1 | Data option A, B or C? | Decide after 7A.4 and 7B. Start with A as the working assumption; never C |
| Q2 | Where does the new platform run for production: the staging-class server grown up, or the existing live servers? | A new server of the same shape as staging; live servers stay untouched until Phase 8 |
| Q3 | If a rollback happens after new messages arrived on the new side, accept loss of the window's messages or copy them back? | Copy back (option B) or none lost (option A); never silently drop |
| Q4 | Watch period per channel | 72 hours for WhatsApp, 72 hours for Facebook, 7 days for Instagram, each with the thresholds in the runbook |
| Q5 | Window times and announcement: who is told, how | Quietest hours; a short notice to organizations at least 48 hours ahead; I draft with placeholders |
| Q6 | Are the restored copies allowed on the staging server, with customer data in them? | Yes only with disk encryption, access limited to you, deleted within 7 days of the last rehearsal |
| Q7 | Cut over staff users first, then one pilot organization, then everyone, as designed? | Yes |
| Q8 | Is a person other than you available during each window to confirm checks on the Meta side? | Strongly recommended |
| Q9 | Facts F1 to F8 | Please send them; the plan is only a template until you do |

## 8. Change log

- 2026-11-28, Claude Code: plan written from MERGE-PLAN, the identity design (sections 7 to 9), the Phase 6 plan and the deployment, backup and delegation docs. No code, no tests, no live access.
