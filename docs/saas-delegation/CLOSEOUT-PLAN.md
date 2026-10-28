# Close-out plan: ManyOsirisChat + SaaS chatbot (Meta approval and healthy delegation)

Written 2026-10-28 for the owner. Same file lives in both repos (SaaS: `implementation/CLOSEOUT-PLAN.md`, Many: `docs/saas-delegation/CLOSEOUT-PLAN.md`); keep them identical.

Repos and branches
- Many: `D:\Projects\Work Projects\The Osiris Labs\ManyOsirisChat`, branch `feature/saas-delegation` (head 13c7873; T1 fixes already committed in ed91c04).
- SaaS: `...\SAAS-chats-ai-phase6`, branch `feature/phase-6-channels` (head 5fa72f7), not merged to `main`.
- Contract source of truth: SaaS `implementation/PHASE-06-V2/many-pack/CONTRACT-V1.md` + `CONTRACT-V1.1-DELTA.md`, copied byte-for-byte into Many (`CONTRACT.sha256`).

## Owner decisions recorded

| # | Decision | Status |
|---|---|---|
| D1 | B1: a **green Playwright run is required** before the SaaS merges to `main` | Decided (owner) |
| D2 | Hosting (ADR-007): the SaaS is **already deployed** (VPS, Docker, Caddy, `scripts/deploy.sh`). Close-out only **rebuilds** it. Record ADR-007 as decided | Decided (owner); ADR-007 hosting text recorded in C1; runtime rebuild pending |
| D3 | Deletion across both apps | Recommendation accepted by owner; A16 text approved 2026-10-28; implementation verification pending |
| D4 | Screencasts show Many's native flows per permission plus one delegated conversation; privacy discloses the SaaS | Owner follows recommendation; confirm evidence/recording text before publication |
| D5 | Instagram unsupported-message diff (`59d3442`) | OPEN, must be answered before gate A closes |
| D6 | Expired Meta token file ("popeye access token.txt") | Owner: ignore |

## D3 review: what happens today with deletion

Many (`backend/app/api/routes_instagram.py:210`, `routes_facebook.py:283`, `routes_whatsapp.py:279`)
- `DELETE .../accounts/{id}` (disconnect) only sets status `disconnected` and marks tokens `expired`. Encrypted tokens stay in the database.
- `DELETE .../accounts/{id}/hard` (Instagram) deletes leads, messages, comments, campaigns, tokens and the account. Its documented FK map has no conversations, `saas_forward_events`, `saas_outbound_messages`, `webhook_events` raw payloads, or WhatsApp/Facebook equivalents. `conversations.lead_id` is a non-null FK, so this probably fails or leaves orphans when conversations exist. **Needs a test to prove it (A4).**
- There is no end-customer deletion route, no deauthorize callback, no data-deletion callback. The privacy page promises email-based deletion within 30 days with no code behind it.
- `saas_forward_events` clears failed payloads after 7 days and removes rows after 30; `webhook_events` raw bodies have no purge found.

SaaS (`apps/api/app/contacts/router.py:425`, `tenants/deletion.py`)
- `DELETE /contacts/{id}?erase_messages=` exists but needs an admin staff session plus CSRF. Many cannot call it.
- Channel event payloads are purged by the A14 retention job (tenant cutoff and 30 days), not on erasure.
- Whole-tenant deletion exists and purges storage.

Gap: a person who asks Many to delete their data gets deleted in Many only if an operator does it by hand, and the SaaS copy is never touched.

Recommendation
1. Meta **deauthorize callback** (`signed_request` verified with the app secret): disconnect the account(s) of that Meta user, delete their stored tokens, turn delegation off for those channels. Idempotent, always returns 200 after verification.
2. Meta **data-deletion callback** returns `{url, confirmation_code}` pointing at a public status page. It covers the connecting business admin's stored data (tokens, profile, accounts).
3. **End-customer erasure** (people who messaged a business): one admin action in Many by channel + external id, deleting lead, conversations, messages, raw webhook payloads and queued `saas_forward_events`. For delegated channels it also queues a signed **`contact.erasure`** event (contract amendment A16: `connection_id`, `external_contact_id`, `event_id`). The SaaS receiver validates it like any event, finds the contact through the connection's tenant and identity, deletes contact + messages + stored `channel_events` payloads for that identity, audits it, returns 202; Many retries like other events.
4. Interim until A16 ships: operator runbook (email → Many erase → SaaS admin `erase_contact` with `erase_messages=true`) written into the privacy page process and `docs/`.
5. Make the 30-day promise real: add a scheduled purge of `webhook_events` raw bodies and report counts.

## Ranked backlog (P0 blocks approval or safe go-live)

| ID | Pri | Item | Repo | Batch |
|---|---|---|---|---|
| R1 | P0 | PARTIAL: signed callbacks, durable operator ledger/status, verified mapped token revocation; automatic OAuth subject mapping and full FB/WA admin erasure unresolved | Many | B |
| R2 | P0 | IMPLEMENTED: A16 producer/receiver, hashed dedupe, runbooks; Many 87 / SaaS 78 distinct latest targeted passes. Full integrated/live verification pending; Many in-flight quiescence remains operational requirement | Many + SaaS | B, C |
| R3 | P0 | Draft policies implemented in both apps with processor/retention/erasure wording; targeted type/browser checks pass. Owner publication review pending | Many + SaaS | B, C |
| R4 | P0 | [x] Key template + API/worker Compose passthrough, fail-closed backup, actual DOMAIN public URL and worker wiring documented;6 source checks pass. Runtime rebuild UNVERIFIED | SaaS | C |
| R5 | P0 | Phase 6 merge to `main` with green Playwright (D1) | SaaS | C |
| R6 | P0 | Business Verification + Tech Provider status (long lead; **start now**) | Meta | E (start day 1) |
| R7 | P0 | Meta dashboard settings and real permission sets for Facebook and WhatsApp; remove `pages_manage_engagement` | Meta | E |
| R8 | P0 | Graph `v21.0` possibly sunset: check changelog, bump, retest | Many | A |
| R9 | P0 | [x] Migration 0019 guards/drift checks; actual empty?head, 0022?head and downgrade/upgrade pass (A2 evidence; independent review) | Many | A |
| R10 | P0 | Fixture repairs: 66 targeted cases pass in latest execution across retained attempts; final full suite pending | Many | A |
| R11 | P1 | [x] T1 fixes committed as ed91c04; A1 rerun: 418 passed, 0 failures/errors/skips (a1-evidence/tests.xml) | Many | A |
| R12 | P1 | Instagram diff decision (D5) | Many | A |
| R13 | P1 | [x] Raw forwarding headers ignored; explicit proxy peers replace wildcard (25 focused pytest tests; A6 review) | Many | A |
| R14 | P1 | [x] UTF-8 byte compare_digest with rejection/call regression tests (A6 evidence) | Many | A |
| R15 | P1 | [x] Read-only selected-channel HTTPS/secret-presence/enabled checks + independent beat observation (20 canary tests; A7 review) | Many | A |
| R16 | P1 | Canary on staging with rotation drill, replay, 429, expiry, take-over, rollback | Both | D |
| R17 | P1 | AI policy wording (business support only), 24 h window (no human-agent tag) in review text | Many/Meta | B, E |
| R18 | P1 | IMPLEMENTED repairs: 31 targeted API passes; 17 distinct latest Playwright passes include all 12 historical failures. Full suites/D1 gate deferred to new session | SaaS | C |
| R19 | P2 | CSV phone guard `-1-1`; health-poll index; `alembic check` drift (`bots.uq_bots_widget_locator`, `provisioning_requests`); undefined S10; `webhook_unhealthy` provider-global; CI workflow never run | Both | A, C |

## Batches

Order: A, B, C may run in parallel (different files; B and C touch only the contract amendment together, owned by C-lead). D needs A, B, C. E recording needs D. F needs E. R6 starts immediately and is owner-run.

### Batch A: Many integrity (Many repo)
Tickets
- A1 commit T1 fixes (R11). Re-run `tests/test_saas_*.py`.
- A2 guard migration 0019 (idempotent add column/constraint, verify type/default, no-op on correct DBs); verify empty→head, 0022→head, downgrade/upgrade (R9).
- A3 repair the 13 fixtures (6 webhook processing, 3 message retry, 4 private reply), the 8 token-refresh fixtures, remaining stale assertions in `t0-evidence/FAILURES.md` (R10).
- A4 add a hard-delete test with conversations present; fix whatever it proves (R1/R2 dependency).
- A5 Graph version bump after checking Meta changelog (R8): config, tests, docs.
- A6 forwarded-IP trust and verify-token `compare_digest` (R13, R14).
- A7 preflight delegation checks (R15).
- A8 owner answers D5; then confirm or drop the Instagram commit.
Gate A: full Many suite results listed (pass count, every remaining failure explained), migration evidence, nothing pushed.

### Batch B: Meta compliance, Many side (Many repo)
- B1 deauthorize + data-deletion callbacks, `signed_request` verification, status page, tests (R1).
- B2 end-customer erasure service + admin route + `webhook_events` purge task; delegated channels queue `contact.erasure` (R2). Blocked on C2 for the receiver, but the Many half can be built against the fake SaaS.
- B3 privacy and terms rewrite (SaaS processor, retention reality, deletion routes, 24 h window, AI disclosure) (R3, R17).
- B4 update `docs/meta-app-review-submission.md` (remove unverified claims, delegation description, A16).
Gate B: owner reads policy text; callback tests green; contract amendment text agreed.

### Batch C: SaaS readiness (SaaS repo)
- C1 record ADR-007 as decided (VPS/Docker/Caddy) in `DECISIONS.md`; no code.
- C2 contract A16 `contact.erasure`: receiver, tenant-scoped erase by identity, payload purge, audit, tests with tenant A/B; update contract copy and `CONTRACT.sha256` in both repos (owner of the contract text for both repos).
- C3 rebuild readiness (R4): add `CHANNEL_SECRET_ENCRYPTION_KEYS` to `.env.production.example` and `DEPLOY.md` (generation command, never print), confirm worker covers channel health and outbound jobs, migration plan 0022→0030 with pre-deploy dump, rollback note (migrations 0023/0024 roll back by pausing, per docs/16).
- C4 triage the 2 API and 12 Playwright failures; fix or document each; run the **full Playwright suite green** (D1) (R5, R18).
- C5 P2 follow-ups (R19) and SaaS privacy/terms wording as processor (R3).
- C6 merge plan: rebase or merge `origin/main`, rerun everything, then request owner sign-off to merge. **No merge without sign-off.**
Gate C: green Playwright log, migration rehearsal on a disposable DB, owner sign-off to merge.

### Batch D: Staging canary (both, live; owner approval per live action)
Follow `docs/saas-delegation/CANARY.md`. Add: erasure end-to-end (Many → SaaS), deauthorize callback with a test user, rotation drill both directions, failed-event replay, `channel.status` and heartbeat, nginx 429, take-over block, rollback by disabling delegation. Record exact commands and outcomes. Gate D: evidence file signed off.

### Batch E: Meta dashboard and evidence (owner + one agent)
Settings checklist (pack section 6), permission sets confirmed from the dashboard, webhook field subscriptions, deletion/deauth URLs, reviewer accounts, screencasts with `META_MOCK_PRIVATE_REPLIES=false` and one real call per permission. D4 confirmed here. Gate E: checklist ticked, owner approves recordings.

### Batch F: Submit and go live
Submit, answer reviewer questions, after approval enable delegation per channel (WhatsApp first), monitoring and rollback runbook. Gate F: Meta approval.

## How to run this with subagents

The lead is the main Claude session. It owns the plan, merges results, and talks to the owner. Workers are subagents started by the lead, one per ticket group, only after the owner says go for that batch.

Rules for every worker
1. Read first: repo `AGENTS.md` or `CLAUDE.md`, this file, the contract files, and the files named in the ticket.
2. Work in an isolated git worktree of the right repo (`isolation: "worktree"`) on a branch named `closeout/<ticket>`; never touch the main checkout, never push, merge, deploy, call Meta/OpenAI/SaaS, or use paid APIs.
3. Own only the files listed for the ticket. If a change is needed elsewhere, report it instead of making it.
4. Tests: disposable databases only. Many tests use the T0 harness (`docs/saas-delegation/t0-evidence/harness/`); **give each worker its own database name** (`many_test_<ticket>`) so parallel runs do not clobber each other, and one Redis namespace per run. SaaS tests use their own throwaway DB per worker.
5. Never fabricate results. Report exact commands, counts and failures; mark anything not run as UNVERIFIED.
6. Final report format: files changed, tests added, command + outcome, open questions, risks. Do not commit unless the ticket says so.

Suggested parallel groups
- Group 1 (Many, files: migrations, tests/conftest, failing test files): A2, A3, A4.
- Group 2 (Many, files: config, middleware, preflight, webhook route): A5, A6, A7.
- Group 3 (Many, files: callbacks, privacy/terms pages, review pack): B1, B3, B4.
- Group 4 (Many, files: erasure service, purge task): B2.
- Group 5 (SaaS, files: channels receiver, contacts erasure, contract docs): C2.
- Group 6 (SaaS, files: deploy docs, env example, decisions): C1, C3.
- Group 7 (SaaS, files: tests and web): C4, C5.
- Groups 1 to 7 do not share files, so they can run together. B2 and C2 meet at the contract; the lead writes the A16 text first, then starts both.
- Reviewer agent (read-only) after each batch: re-verifies the batch's claims against the code and the evidence before the owner gate.

Lead responsibilities
- Write the A16 contract text and update both contract copies and `CONTRACT.sha256` in one step.
- Merge worker branches into the batch branch in order, rerun the batch tests, update `PROGRESS.md` in each repo, then stop for the owner gate.
- Keep this file's backlog table current; tick an item only with evidence.

## Current owner execution update ? 2026-10-28

This update supersedes earlier requirements to wait for a separate go or stop
at every batch gate: proceed through all batches autonomously, run related
checks for each change, and run the full suites once after local integration.
Repeat tests only when new changes or failures justify it. It does not authorize
pushes, main merges, deployment, live sends, paid calls, authenticated external
service calls, or cloud resources. Public Meta documentation lookup is approved.
D5 is deferred by the owner: leave OPEN and report at Batch A completion.
A16 approved by owner and adopted locally in synchronized contracts/manifests.
Text: Many `docs/saas-delegation/A16-PROPOSED.md` (historic name; ADOPTED status).
Many commit bfb1cc8, SaaS batch-c205bdab; producer/receiver verification pending.

Starting-state correction: Many was clean at 13c7873; T0?T6 are already
committed and pushed (owner clarification), and T1 fixes are in ed91c04.
SaaS phase6 was clean at 5fa72f7. A1 rerun passed 418 tests, with no
failures/errors/skips, 92.99 seconds. See Many PROGRESS.md and a1-evidence.
No duplicate T1 code commit is required.

Groups 1/2/6 started first, isolated branches closeout/a2-a4, closeout/a5-a7,
closeout/c1-c3. Group 6 ownership additionally includes compose.prod.yaml and
scripts/deploy.sh because inspection found missing API/worker key passthrough
and a deployment script that only warned on a failed predeploy backup. Runtime
rebuild/deployment remains UNVERIFIED and unapproved. Shared progress, plan,
contract adoption and integrations belong to the lead. Initial read-only review
found one A2 SQL-literal normalization defect, fixed and regression-tested; final
review found no remaining blocking/high/medium issues in A2?A4/A6?A7/C1/C3.
Worker commits: Many afb604f and 6e80eaa, SaaS3347a02. Integrated local batch
branches: Many closeout/batch-a0ca1c67, SaaS closeout/batch-c216a4f0.
No full integrated suite yet; no main merge, push, deployment or live call.
B1/B3/B4 worker completed related callback, migration and two-page TypeScript
checks; B1 remains PARTIAL. Lead additionally fixed CLI initialization exception
sanitization (1 focused test passed) and named upsert-constraint/index drift
validation (5 standalone migration assertions passed). Independent review of
these new changes is pending. B2/C2 and C4/C5 subsequently completed; final update below supersedes this intermediate state.
Owner approved shared dedupe-key hashing plus migration to remove legacy raw
IDs/fallback text without an Instagram dispatch/send-handler refactor. Worker
implementation and focused replay/privacy tests subsequently passed; full
integrated/live verification remains pending.

The synchronized SaaS plan copy is in SAAS-chats-ai/implementation, not the
SAAS-chats-ai-phase6 checkout. Keep the two existing copies byte-identical.

## Final implementation handoff ? 2026-10-28

Latest owner instruction: finish the three remaining implementations, then give
an exact prompt for full testing in a NEW SESSION. No full integrated suites
were run after this instruction. The three fixes are complete and reviewed:
hashed processed keys/migration0029; erasure race/recipient safety with SaaS0031;
and the remaining knowledge/overview Playwright repairs.

Final independent review: no remaining blocking/high/medium findings in reviewed
scope. Many B2 focused10+3 passes,87distinct latest passing cases; SaaS C2 final
32focused passes,78distinct latest passing cases; C4/C5 API31passes and17distinct
latest targeted Playwright passes. These are iterative targeted results, not
full green suites. Evidence and remaining limits: FINAL-IMPLEMENTATION-REVIEW.md.

Integrated application bases: Many closeout/batch-b33bde97, SaaS
closeout/batch-c1ee703e; only final lead documentation/source-check updates follow.
Full testing prompt: Many docs/saas-delegation/TESTING-HANDOFF.md. Single source
migration heads: Many0029_hash_processed_event_keys; SaaS0031_contact_erasure.

Still OPEN: D5 (owner deferred), A5 primary Graph-version evidence (official429),
R1 automatic Meta admin mapping/full FBWA admin erasure, full integrated suites,
D1 full Playwright gate, staging/live canary, owner-run Meta verification/settings,
main merge/rebuild/deployment/submission approvals. No release gate is closed by
targeted tests. No push, main merge, deployment, live send or paid call occurred.

## Standing rules
No push, merge, deploy, live send or paid call without separate approval. Meta tokens and webhooks stay in Many only. Tenant scope on every SaaS query, with A/B tests. Alembic migrations only. Record exact commands and outcomes in `PROGRESS.md`.
