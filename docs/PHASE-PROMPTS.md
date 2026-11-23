# Phase prompts (copy one per session)

How to use: start a new Claude Code session with the new repo attached (plus ManyOsirisChat and Saas-Chatbot attached read-only for reference). Paste the COMMON PREAMBLE first, then one phase prompt. When the phase ends, paste the report back in the planning chat.
Placeholders: business-mind = your repo name. Do not put tokens or secrets in any prompt.

## COMMON PREAMBLE (paste at the start of every phase)

You are working on the merge of ManyOsirisChat (Many, Meta gateway) and Saas-Chatbot (SaaS) into one platform in the repo business-mind. Read docs/MERGE-PLAN.md, docs/MERGE-PROGRESS.md and CLAUDE.md first; they are binding.
Rules:
1. The old repos (ManyOsirisChat, Saas-Chatbot) are read-only references. Never modify or push to them.
2. Never open, print or commit any .env, token or secret (including `popeye access token.txt`). If you see a real secret, report it, do not use it. No live Meta tokens, webhooks or databases; no real Meta or OpenAI calls. Throwaway databases only; print the DB host/name before every test run and set APP_ENV=test and TEST_DATABASE_URL explicitly.
3. Instagram receive/dispatch/send code is frozen. Do not edit it. If a task seems to need an edit there, STOP and ask me. Any approved edit must be tiny, tested with the feature flag off to prove identical behavior, and reversible.
4. Plan first: before changing anything, show me the plan and the exact changes and wait for my OK. After I approve, do not re-ask for each step.
5. Reversible changes only: back up first, move instead of delete. Work on the session's feature branch, never push main, no force-push, no tags. When done, push the branch and open a DRAFT PR (use the repo PR template if one exists).
6. Never invent results. Report exact commands and their real outcomes. If something fails or is skipped, say so.
7. Ask before producing big outputs I did not request.
8. At the end update docs/MERGE-PROGRESS.md (done / in progress / next) and give the FINAL REPORT in this format: Goal; What changed (files/areas); Commands run + results; Exit criteria met yes/no each; Open problems; Decisions I need from you; Next phase readiness.

---

## PHASE 1: Foundation

Goal: business-mind contains Many as the root and the SaaS under modules/saas/, both with full git history, with tests passing and the new rules in place.
Tasks:
1. Verify business-mind contains only the bootstrap docs (CLAUDE.md, docs/MERGE-PLAN.md, docs/MERGE-PROGRESS.md, docs/PHASE-PROMPTS.md). If anything else is there, STOP. Keep this repo's CLAUDE.md; move the old repos' CLAUDE.md/AGENTS.md to docs/legacy/.
2. Show me the import plan first: which tool (git subtree or git filter-repo, prefer the simplest that keeps history), how the SaaS maps to modules/saas/{api,worker,web}, how Many stays as backend/, dashboard/, nginx/ etc., and how name clashes (docker-compose files, scripts, docs, .github, .gitignore, CLAUDE.md, AGENTS.md) are resolved. Wait for my OK.
3. Import Many (root) and the SaaS (modules/saas/) with history. Do not edit their code.
4. Add: new CLAUDE.md (rules above), docs/MERGE-PLAN.md (from my plan), docs/MERGE-PROGRESS.md, docs/IMPORT-NOTES.md (what was imported, commit ids, clashes and how solved). Move the old repos' own CLAUDE.md/AGENTS.md to docs/legacy/ with a note.
5. Add a local-only compose (docker-compose.merge-dev.yml) with throwaway Postgres 15, Postgres 17+pgvector, Redis. No real secrets; example env file only.
6. Run Many's backend tests and the SaaS API tests (and the web unit/lint/typecheck) in the new repo. Compare with the results in the original repos (run those too, read-only) and explain any differences.
Exit criteria: history present for both (show `git log --oneline` counts and a sample of old commits); both suites match the originals; draft PR open; no secrets committed (run a secret scan).

## PHASE 2: One infrastructure

Goal: one stack starts with one command; Many and the SaaS talk over the internal network using the existing signed contract.
Tasks:
1. Design first, wait for OK: a single compose (dev and prod variants), one reverse proxy layout (Many nginx routes /api/saas/* and the SaaS web/API), network names, health checks, one env scheme with .env.example only, one deploy script outline. Keep both migration chains and both databases.
2. Implement it. Do not change Instagram code. Do not change the contract text; run scripts/check_contract_copies.py and keep it passing (update the pinned copy paths only if the move required it, and say so).
3. Add a mock end-to-end test: mock Instagram webhook (existing script) -> Many -> SaaS -> reply back through Many, with Meta and OpenAI mocked. Also WhatsApp and Facebook mock paths.
4. Document start/stop/reset in docs/RUNBOOK-DEV.md.
Exit criteria: `docker compose up` brings up everything healthy; mock e2e passes for all three channels; both suites still pass; contract check passes.

## PHASE 3: One identity

Goal: one login reaches every page; roles and tenants are mapped safely.
Tasks:
1. Read both user/session/tenant models and write a design doc docs/IDENTITY-DESIGN.md: SSO approach first (log in once), then single user record, Many workspace <-> SaaS tenant mapping, role mapping (owner/admin/operator/viewer to SaaS roles and platform staff), duplicate emails, session lifetime, logout everywhere, password reset, audit. Include migration (reversible) and rollback. Wait for my OK.
2. Implement SSO and the mapping behind a feature flag (default off = today's behaviour).
3. Tests: role matrix for every route (allowed and forbidden), tenant isolation (user A cannot read tenant B), session expiry, logout, duplicate email handling.
4. Security review of the diff (use /security-review) and fix findings.
Exit criteria: all tests pass; flag off = identical behavior (proven by tests); isolation tests pass; written review attached.

## PHASE 4: One dashboard

Goal: one app with one menu containing every tab of both apps, Instagram included as a channel.
Tasks:
1. Inventory every page of Many's dashboard and the SaaS web app into docs/UI-INVENTORY.md (route, purpose, API used, role). Propose the new information architecture (menu tree, naming, RTL/language handling, theme) and a mockup description. Wait for my OK.
2. SaaS Next 16 app is the shell. Port Many's pages as modules (Overview, Accounts, Campaigns, Facebook campaigns, Leads, Logs, WhatsApp pages, Instagram accounts). Keep the old API calls; do not change Instagram backend code. For delegated channels hide Many's Conversations/Take Over and use the SaaS inbox.
3. Shared layout, auth guard (from phase 3), channel switcher, consistent empty/error/loading states.
4. Tests: Playwright smoke test per page, typecheck, lint, build. Screenshots of every page in desktop and mobile width (saved under docs/ui-screenshots/, tell me the path).
Exit criteria: checklist showing every old tab has a place; smoke tests pass; build passes.

## PHASE 5: Unified data and behaviour

Goal: leads/contacts linked, one inbox per customer, one erasure flow, combined analytics.
Tasks:
1. Design doc docs/DATA-UNIFICATION.md: link Many leads to SaaS contacts by channel identity (channel + external id), duplicate rules, one customer timeline across channels, one erasure flow covering both systems (Many Meta account erasure and SaaS contact erasure), combined analytics (messages, leads, bot answers, costs), one audit trail. Wait for my OK.
2. Implement with reversible migrations chained on the real heads (check `alembic heads` in both chains; do not trust notes in docs).
3. Tests: no duplicate links on a synthetic dataset, erasure removes data in both parts, idempotent re-runs, tenant isolation.
Exit criteria: all tests pass; erasure proven end to end on test data; migrations upgrade and downgrade cleanly.

## PHASE 6: Staging and hardening

Goal: a staging environment proves the platform with the Meta test number only.
Tasks:
1. List what I must prepare (server, domain, test number, secrets stored outside git). Do not create cloud resources or deploy without my separate approval. Provide the deploy runbook docs/STAGING.md.
2. Close open items: backup and restore drill (restore on a clean machine and verify), alert receiver (health and error alerts to a real destination), security review, load check at expected traffic with numbers.
3. End-to-end tests: WhatsApp, Facebook, Instagram on test number/mock; Instagram with delegation flag on a TEST account only.
4. Write docs/TEST-REPORT.md with real numbers.
Exit criteria: restore drill passes; no open critical findings; test report complete; one-week soak plan agreed.

## PHASE 7: Data rehearsal and cutover

Goal: production data moved safely, channel by channel.
Tasks:
1. Rehearsal: using COPIES of backups only (I will provide them; never connect to live DBs), run the merged migrations and user mapping in staging, compare row counts and key invariants, time it, list conflicts (duplicate emails, role mismatches). Write docs/CUTOVER-RUNBOOK.md with exact steps, timings, go/no-go checklist, rollback steps per channel.
2. Cutover is executed by me following the runbook. You prepare commands and verify each step with me; you never switch Meta webhooks or DNS yourself.
3. Order: WhatsApp, then Facebook, then Instagram last. Instagram only after I give explicit written approval in this chat.
Exit criteria: rehearsal report with real numbers; runbook reviewed by me; each channel's watch period result.

## PHASE 8: Stabilise and retire

Goal: old apps retired safely.
Tasks:
1. Watch checklist for 2 to 4 weeks (errors, delivery status, latency, quota, bot answer quality) with daily commands I can run.
2. Prepare the retirement checklist: archive old repos (do not delete), stop old stacks only after my OK, keep backups, revoke the old Meta token and rotate secrets, update docs. List what I must do myself at Meta and at the server.
3. Final docs cleanup: remove duplicated erasure/deploy files only after confirming they are unused; move rather than delete.
Exit criteria: checklist signed off by me; old apps archived; MERGE-PROGRESS.md shows all phases done.
