# Merge plan: ManyOsirisChat + Saas-Chatbot → one platform

Status: APPROVED plan (phases 0-9). Old repos are untouched.
`docs/MERGE-PROGRESS.md` tracks done / in progress / next.

## Goal
One application: one login, one dashboard, one deploy. Many (Meta gateway: Instagram, Facebook, WhatsApp, campaigns, leads) stays the root.
The SaaS (bots, knowledge base, retrieval, quotas, analytics, team) comes in as a module, unchanged at first. The two parts talk to each other inside the platform.

## Ground rules (apply to every phase)
1. The live Many and SaaS apps and their repos are never modified. Critical fixes there are copied into the new repo by hand until cutover.
2. The new repo never uses live Meta tokens, live webhooks or live databases. It uses throwaway databases, the Meta test number and mock webhooks.
3. Instagram dispatch/send code is not touched without the owner's explicit OK.
4. Each phase ends with a short report (what changed, exact commands, results) and waits for "continue".
5. Reversible changes only: back up first, move instead of delete. Pushes go to a feature branch with a draft PR. No push to main, no deploy, no paid API calls without separate approval.
6. No invented results: every claim comes with the command that produced it.

## Phase 0: Decisions and repo (owner)
Work: create an empty private GitHub repo and give me its name; confirm the ground rules; confirm the open choices below.
Exit: repo attached and empty; choices recorded in MERGE-PROGRESS.md.
Instagram policy (agreed): option 2. Instagram receive/dispatch/send code stays frozen; any change is small, explained, tested with the flag off, reversible, and needs the owner's OK each time. Instagram joins the same organization model as Facebook and WhatsApp (tenant + bot per account, per-account delegation flag), tested on a test account first, and is the last channel to cut over.
Open choices (defaults in brackets): SaaS Next 16 as the dashboard shell [yes]; Postgres 15 and 17 kept separate at first [yes]; end customers get no login, only clients and staff [confirm]; may Instagram code be touched later [no, ask each time].

## Phase 1: Foundation
Work:
1. Copy Many into the new repo with full history as the root.
2. Add the SaaS under `modules/saas/` (api, worker, web) with history, code unchanged.
3. Add the new CLAUDE.md (rules above), `MERGE-PLAN.md`, `MERGE-PROGRESS.md`.
4. Add a local-only combined compose with throwaway Postgres 15, Postgres 17 + pgvector and Redis.
5. Run both full test suites inside the new repo.
Exit: both suites pass with the same results as in the original repos, or any differences are explained; draft PR open.

## Phase 2: One infrastructure
Work: one reverse proxy (Many's nginx routes `/api/saas/*` and the SaaS web to the module); one `.env` scheme with secrets kept out of git; one deploy script; the existing signed contract between Many and SaaS runs over the internal network; health checks for both.
Exit: `docker compose up` starts everything; a mock Instagram webhook goes Many → SaaS → reply back through Many on a throwaway stack; contract copies check passes.

## Phase 3: One identity
Work: single sign-on first (log in once, open both parts); then map Many workspaces to SaaS tenants and Many roles (owner, admin, operator, viewer) to SaaS roles; resolve duplicate emails; define one user record.
Exit: one login reaches every page; role matrix tested for every route (allowed and forbidden cases); no user can see another tenant's data (isolation tests).

## Phase 4: One dashboard
Work: SaaS web app becomes the shell. Many's pages move in as modules: Overview, Accounts, Campaigns, Facebook campaigns, Leads, Logs, WhatsApp. SaaS pages stay: bots, knowledge, conversations, analytics, team. One menu, one theme, one language/RTL handling. Retire Many's Conversations / Take Over page for delegated channels (the SaaS inbox is used there).
Exit: every old tab has a place in the new menu (checklist with screenshots); each page works against the right backend; Playwright smoke tests pass.

## Phase 5: Unified data and behaviour
Work: link Many leads and SaaS contacts by channel identity; one inbox view per customer across channels; one data-erasure flow that covers both systems; combined analytics (messages, leads, bot answers, costs); one audit trail.
Exit: erasing a person removes data in both parts (tested); the lead/contact link has no duplicates on a restored copy of data.

## Phase 6: Staging and hardening
Work: staging on its own server and database with the Meta test number; end-to-end tests for WhatsApp, Facebook and Instagram on the test number; load check; the open SaaS items: backup/restore drill, alert receiver, security review; a one-week soak with test traffic.
Exit: written test report; no open critical findings; backup restored successfully on a clean machine.

## Phase 7: Data rehearsal and cutover
Work: restore copies of both live databases into staging, run the merged migrations and user mapping, compare row counts, time the migration. Then cut over one channel at a time with a fresh backup and a short announced window: WhatsApp first, Facebook second, Instagram last, each only with the owner's explicit approval. For each: switch the Meta webhook URL and DNS, watch health, keep the rollback ready.
Exit: each channel runs on the new platform for the agreed watch period with no regressions.

## Phase 8: Stabilise and retire
Work: keep the old apps deployed and idle for 2 to 4 weeks as rollback; then archive the old repos (not delete), remove old VPS stacks, keep backups, revoke the old Meta token and rotate secrets.
Exit: old apps retired; the platform is the only live system.

## Phase 9 (optional, later decision): single backend
Merge the two backends into one service. Only if it is still worth it after Phase 8. Needs a separate plan and owner approval, especially for Instagram code.

## Risks and how the plan handles them
- Live Instagram breaks: it is not touched until the last cutover step, and has a rollback.
- Data mix-up between tenants: isolation tests in Phase 3 and 5.
- Postgres version difference: separate databases until Phase 7, then a rehearsed move.
- Fixes made in the live apps during the build: copied across manually and logged.
- Scope creep: new features wait until after Phase 8.

## Open items outside the plan
Revoke the old Meta token file at Meta; the stale CLAUDE.md note in Many (migration head says 0022, the real head is 0030).
