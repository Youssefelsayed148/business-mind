# Phase 5 plan: unified data and behaviour

Status: **plan approved 2026-11-28 (owner accepted Q1 to Q7 as recommended and approved merging PRs #11 and #12, both merged). Step 5.0 design: `docs/DATA-UNIFICATION.md`, awaiting review.** Written 2026-11-27 from a read of the code
(nothing here was run or tested). Facts marked "read" come from files; "owner-reported" comes from
the owner's message and was not observed by me.

Goal (MERGE-PLAN): link Many leads and SaaS contacts by channel identity; one inbox view per
customer across channels; one data-erasure flow covering both systems; combined analytics
(messages, leads, bot answers, costs); one audit trail.

Exit (MERGE-PLAN): erasing a person removes data in both parts (tested); the lead/contact link
has no duplicates on a restored copy of data.

## 1. Where things stand

- Phase 4 is built and pushed (draft PR #12 into `docs/phase-4-plan`, PR #11 under it). The owner
  reports that the WSL gates passed (owner-reported; the results are not in the repo yet).
  Merge order proposed: #11, then #12, then branch Phase 5 from the new `main`.
- Rules that apply (CLAUDE.md): Instagram receive, dispatch and send code is frozen; reversible
  migrations only, chained on the real Alembic heads (Many `0031_sso_link`, SaaS
  `0035_invitation_locations`, read 2026-11-26, re-check with `alembic heads`); throwaway
  databases only; no live Meta or OpenAI; plan first.

## 2. What the code already has (read)

| Topic | Many | SaaS |
|---|---|---|
| Person record | `leads` (`platform`, one account column per platform, `ig_user_id` holds the Instagram, Facebook or WhatsApp external id; one unique constraint per platform) and `whatsapp_contacts` (`wa_id`, consent, optional `lead_id`) | `contacts` and `contact_identities` (`tenant_id`, `contact_id`, `channel`, `external_id`, `connection_id`) |
| Cross-system key | `saas_delegation` and `saas_forward_events` send Many events to the SaaS by connection | `channel_connections` (`many_channel_ref`) and `channel_events` receive them |
| Erasure | `services/contact_erasure.py`: one transaction per channel contact, then a content-free `contact.erasure` event forwarded to the SaaS (outbox, idempotent by request id). Runbook: `docs/end-customer-erasure-runbook.md` ("local implementation and fake-SaaS tests only; live execution UNVERIFIED") | `channels/erasure.py`: transactional erase with an erasure fence of identity digests; contact erase route in `contacts/router.py` |
| Audit | `audit_log` (actor, action, entity, severity, metadata) | `audit_events` (tenant, actor, action, target, metadata) |
| Cost or usage | none found (no cost columns on messages or automation logs) | `usage_events` (kind, message, conversation, payload) |

Consequences for the design:

1. For **delegated** channels the SaaS already holds a contact whose identity is the same external
   id Many has. The link is mostly a mapping, not a new identity.
2. For **non-delegated** channels (Many answers natively) there is a Many lead and no SaaS
   contact. These are the people the link must reach.
3. Erasure today goes **Many to SaaS only**. There is no flow that starts from the SaaS and
   reaches Many, and no single place that shows both halves done.
4. "Costs" exist only on the SaaS side. Many has nothing to merge. The design must say what
   "combined costs" means.
5. The two databases stay separate until Phase 7, so a join in SQL is not possible. Anything
   combined is an API read or a copied read model.

## 3. Decisions for the owner (with my recommendations)

| # | Question | Recommendation |
|---|---|---|
| Q1 | Where does the lead-to-contact link live? (a) A SaaS-side table filled from Many reads. (b) A column on Many leads. | (a). No Many or Instagram schema change; reversible by dropping one table. |
| Q2 | How strict is "same person"? | Link only on the same channel identity (channel, account or connection, external id). Never match by phone or name across channels. A person on two channels stays two links until staff merge them (the SaaS merge route exists). Matches the erasure runbook's "never merge identities across workspaces". |
| Q3 | Customer timeline across channels | Read-only, staff and Owner/Admin first: one view per SaaS contact that adds Many conversations for linked non-delegated channels. No writes into Many. |
| Q4 | Erasure entry point | One request started in the SaaS (Owner or Admin, verified requester), which erases the SaaS side and calls the existing Many erasure for each linked identity, with one case record (request id, per-side status, retry). The existing Many-to-SaaS direction stays. |
| Q5 | "Combined analytics" | Message counts, leads, bot answers and AI usage side by side per organization. Many has no costs, so "costs" = SaaS AI usage only, labelled as such. Any Many cost data is a later feature. |
| Q6 | "One audit trail" | A read view in the SaaS (staff and Owner/Admin) that shows SaaS audit events plus Many audit entries for the mapped workspace. Both systems keep writing their own store. No copying of audit rows. |
| Q7 | Instagram | Reads only. The erasure call goes through Many's existing erasure service, not through frozen send/receive code. If any step needs a frozen file edit: STOP and ask. |

## 4. Steps (one branch and one draft PR each, stop for review after each)

| Step | Content | Done when |
|---|---|---|
| 5.0 Design | `docs/DATA-UNIFICATION.md` (what is read, Q1 to Q7 answered, data model, API, failure cases). Docs only. | Owner approves |
| 5A Link (built 2026-11-28, in review) | SaaS table for links, reversible migration, deterministic job that fills it from Many reads through the internal call, backfill idempotent, duplicate and conflict rules | Synthetic dataset: no duplicates, re-run changes nothing, tenant isolation tests; the same on a restored copy |
| 5B Timeline (built 2026-11-28, in review; the client view of the link, without Many conversation text) | Contact page in the SaaS shows linked Many conversations (read only) | Role and tenant tests, browser spec |
| 5C Erasure (built 2026-11-28, in review) | One SaaS-started flow, per-side status, retries, tests with fakes first | Erasing a person removes data in both parts on test data; idempotent re-run; failure of one side is visible and retryable |
| 5D Analytics (built 2026-11-28, in review) | Combined read model and page | Numbers equal the sources on a fixed dataset |
| 5E Audit (built 2026-11-28, in review) | Combined read view | Role and isolation tests |
| 5F Close | WSL full gates, restored-copy link test, record | Exit criteria |

Gates for every step (as before): both backend suites, script tests, policy and contract copy
checks, `scripts/check_instagram_frozen.py`, `scripts/dev-up.sh test`, web lint, typecheck,
Playwright on Node 24, flags-off proof.

## 5. Risks

- Erasure is destructive and its Many half is UNVERIFIED in a live setting (runbook). Everything
  stays on throwaway data with fakes until the owner approves otherwise.
- A wrong link would show one person's messages to another person's account. Links only on exact
  identity inside one tenant, with a test per case.
- Many reads must go through the allowlisted internal call; new Many routes would need review
  because several Many routes touch frozen Instagram areas.
- The restored-copy test needs copies the owner supplies (never a live database).

## 6. What is left from other phases

| From | Item | Blocks |
|---|---|---|
| Phase 4F | Live edge checks: `scripts/dev-up.sh test` and `e2e/phase2/check_nginx.py` against the new exchange deny (only a static test ran here) | closing Phase 4 |
| Phase 4F | Many suite and the script tests that need the DB socket (22 errors here were a harness mismatch, not code) | closing Phase 4 |
| Phase 4F | Walk of the old dashboard in a browser; gap 10 (nginx paths for the old dashboard in the unified compose) | closing Phase 4 |
| Phase 4F | Screenshots reviewed by a person on a real phone; real Many behind the new pages; real Meta connect flows; real authenticator and email | closing Phase 4 |
| Phase 4 | Next 16.4.3 security notice (the build stops once per session); upgrade not run | owner decision |
| Phase 4 | Public opt-in call needs Many started with `--proxy-headers --forwarded-allow-ips=<SaaS API address>` (documented in the runbook, not set in compose) | before the opt-in link is used |
| Phase 4 | Not ported: leads CSV export, Instagram MockConnect; no location or agency screens; no QR code for the authenticator; delegated conversation rows have no inbox link | owner decision |
| Phase 4 | Review pass on the four agent-written 4C/4D page sets (offered, not run) | recommended before merge |
| Phase 3 review | Items 1 to 7 "open before enabling any flag" (TOTP reuse race, agency grant with deleted locations, limited Admin retention, agency reply design, agency Admin export, invitation existence leak, pending Owner invitation replace) and items 8 to 10 that still block any identity flag | enabling identity flags |
| Phase 3 review | Items 2, 4, 5, 6 noted as open in the Phase 4 plan | same |
| Phase 2 | Internal TLS with a private CA and edge TLS (Phase 6); Many transport pinning (Phase 6); prod overlay written, never deployed | Phase 6 |
| Phase 1/2 | CI is paused (billing); the SaaS workflow never ran; every gate is local | all phases |
| Outside the plan | Revoke the old Meta token at Meta; rotate the webhook secret and verify token; stale note in Many CLAUDE.md (migration head 0022 vs real 0031); Many `requirements.txt` unpinned; root `.gitignore` lacks a root `.env.local`; the public GitHub repository (Phase 0 asked for private) | owner |
| Phase 6 to 9 | Staging, load check, backup and restore drill, alert receiver, security review, soak; data rehearsal and cutover; retire the old apps; optional single backend | later |

## 7. Run on the WSL stack before Phase 5 starts (owner)

1. `scripts/dev-up.sh test` and `e2e/phase2/check_nginx.py` (Phase 4F edge deny).
2. Both backend suites on Postgres 15 and 17, script tests, policy and contract checks,
   `check_instagram_frozen.py`.
3. Web gates on Node 24 (lint, typecheck, build, Playwright).
4. Walk the old dashboard once and note anything that differs.
5. Send me the result files or paste the summary so I can record them in `docs/PHASE-4-PLAN.md`
   section 17 and `docs/MERGE-PROGRESS.md`.

## 8. Change log

- 2026-11-27, Claude Code: plan written from a read of both data models, erasure services, audit
  tables and the earlier phase records. No code, no tests, no migration.
