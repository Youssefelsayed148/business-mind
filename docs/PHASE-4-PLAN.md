# Phase 4 plan: one dashboard

Living plan. Last updated: 2026-11-26 (Claude Code). Base: `main` at `32d32e9`.
Parent: `docs/MERGE-PLAN.md` (Phase 4). Progress record: `docs/MERGE-PROGRESS.md`.

**Status: greenlit for step 1 by the owner on 2026-11-26. Step 1 not started. No Phase 4 code
exists.** Everything below step 1 is a proposal until the owner approves step 1.

## 1. Status

Status values: not started / in progress / in review / done / blocked.

| Step | Branch (suggested) | PR | Status | Done when |
|---|---|---|---|---|
| 1. Inventory and design | `phase-4/inventory` | - | not started | Owner approves the docs and P1 to P8 |
| 4A. Connection | `phase-4/connection` | - | not started | Role and tenant isolation tests pass |
| 4B. Shell | `phase-4/shell` | - | not started | One Many page works end to end |
| 4C. Client pages | `phase-4/client-pages` | - | not started | Client and staff browser tests pass |
| 4D. Staff pages | `phase-4/staff-pages` | - | not started | Every old tab has a place |
| 4E. Identity screens | `phase-4/identity-screens` | - | not started | One login reaches every page the role allows |
| 4F. Close | `phase-4/close` | - | not started | All exit criteria pass |

Each step is one branch and one draft PR, and stops for the owner's review.

## 2. What Phase 4 does

The SaaS web app (`modules/saas/apps/web`, Next 16) becomes the only dashboard: one login, one
menu, one theme, one language/RTL handling. Many's pages (`dashboard/`, Next 14, Tailwind) are
ported into it. SaaS pages stay.

| Who | What they get in the one dashboard |
|---|---|
| Clients | Today's SaaS pages, plus WhatsApp, Facebook campaigns and Facebook/WhatsApp accounts |
| Staff | All of that, plus the Many overview, Instagram accounts and campaigns, leads, logs, messages, conversations |
| Everyone, by role | New screens for team, invitations, password reset, MFA and sessions |

Not in Phase 4: linking leads and contacts or building one inbox across systems (Phase 5),
merging the two backends (Phase 9), new features, APIs to manage locations or agencies,
Instagram backend changes, live Meta, deployment, cutover. The old Many dashboard keeps running
until the owner approves parity.

## 3. Already decided

| Decision | Source |
|---|---|
| SaaS Next 16 app is the shell | MERGE-PLAN.md |
| Many pages that client logins cannot open start as staff-only (overview stats, campaigns, conversations, messages, leads, logs, stats, Instagram) | Owner, 2026-11-26; IDENTITY-DESIGN D1, D2; `backend/app/core/client_scope.py` |
| The public `POST /auth/sso/exchange` is closed once the shell exchanges server-side; Many's own `/auth/login` stays as fallback | IDENTITY-DESIGN D3, R8 |
| Keep the existing Many API calls and behaviour; Instagram receive/dispatch/send code stays frozen | PHASE-PROMPTS, CLAUDE.md rule 3 |
| Many Conversations / Take Over is hidden for delegated channels (the SaaS inbox is used) | MERGE-PLAN.md |
| Clients (Owner, Admin, Manager) edit knowledge; bot configuration stays staff-only | IDENTITY-DESIGN D5 |
| The old Many dashboard is not deleted; move, do not delete | CLAUDE.md rule 5 |

## 4. Decisions needed in step 1

| # | Question | Recommendation | Owner decision |
|---|---|---|---|
| P1 | Where does the server-side proxy to Many live: SaaS API or a Next route handler? | SaaS API: reuses session, CSRF, revocation and audit; strict path allowlist; the Many token never reaches the browser. Note that `next.config.ts` already rewrites `/api/*` to the SaaS API | open |
| P2 | How do staff reach WhatsApp and Facebook? (gap 1) | Staff pick an organization and get an SSO membership for its mapped workspace | open |
| P3 | Styling of ported pages | Rebuild with SaaS components and `tokens.css`; no Tailwind | open |
| P4 | Language | English interface, correct RTL/bidi for content, logical CSS properties; Arabic interface later | open |
| P5 | The Many Messages tab (gap 5) | Keep, staff-only | open |
| P6 | Legal and opt-in pages | Keep every existing URL working; the owner chooses the legal text | open |
| P7 | Which `PHASE-3-REVIEW.md` open items are fixed in 4A? | Items 1 (reused MFA code race), 3 (location-limited Admin changes retention and change requests), 7 (Admin replaces a pending Owner invitation); agency replies (item 4) later. Step 1 states which of the others block enabling a flag | open |
| P8 | When is the old Many dashboard retired? | Keep it running until the owner approves parity; removal belongs to cutover | open |

## 5. Known gaps

Found by reading the code on 2026-11-26. **Not tested**: confirm each with a failing test before
fixing it.

| # | Gap | Where | Handle in |
|---|---|---|---|
| 1 | Staff single sign-on creates no Many workspace membership, but WhatsApp and Facebook routes require one. A linked user who already has an older membership keeps it | `backend/app/services/sso_session.py` (`sync_memberships`), `backend/app/authz.py` | 4A |
| 2 | Nothing writes `tenants.many_workspace_id` / `workspaces.saas_tenant_id`, so client sign-on to Many cannot work. Design 4.1: staff-run mapping command, dry run first. `identity_migrate.py` creates no memberships | `modules/saas/apps/api/app/identity/sso.py`, `sso_session.py` | 4A |
| 3 | A user's SSO membership is one workspace at a time, so two organizations in two tabs flip it | `sso_session.py` | 4A, 4B (switcher) |
| 4 | Location-limited users get no Many access. The Manager role maps to Many `operator`, which lacks the account, contact, template and campaign-run permissions: pages must hide those actions | `sso.py`, `sso_session.py`, `authz.py` | 4B, 4C |
| 5 | The merge plan's page list omits the Many Messages tab | `dashboard/components/layout/Sidebar.tsx` | step 1 (P5) |
| 6 | Instagram connect redirects to `FRONTEND_URL/accounts`; the shell must handle that address without backend changes. The WhatsApp opt-in link uses `DASHBOARD_BASE_URL` (or `APP_BASE_URL`). Check `/privacy`, `/terms` and the Meta SDK connect flows on the new host (Meta app domain settings are an owner action) | `routes_meta.py`, `routes_whatsapp_outreach.py` | 4C, 4D |
| 7 | No web screens for team, invitation acceptance, password reset, MFA or sessions (the APIs exist) | `modules/saas/apps/api/app/identity/` | 4E |
| 8 | No recorded run of the SaaS web Playwright suite in this repo; `format:check` already fails on 4 files | `docs/PHASE-1B-RESULTS.md` | 4B (baseline) |

Size: the Many dashboard is about 8,900 lines. It uses Tailwind and a token in `localStorage`;
the SaaS web app uses its own CSS tokens (light and dark) and a session cookie. Neither app has a
translated interface.

## 6. Steps

**Step 1: inventory and design (docs only, then stop).**
- `docs/UI-INVENTORY.md`: every page of both apps with route, purpose, every API call, required
  role, client or staff, flag dependency and new location. Start from section 7.
- Add to this file: menu tree, naming, organization and channel switchers, theme, language/RTL,
  desktop and mobile mockup description, how the shell reaches Many, rollback.
- Get decisions P1 to P8; confirm or adjust the steps below.

**4A. Connection.** Organization to workspace mapping command; server-side exchange and proxy
(P1); staff workspace access (P2); approved security fixes (P7). Deny-by-default proxy
allowlist: never `/api/saas`, `/saas` or `/webhooks`.

**4B. Shell.** Menu, organization and channel switchers, auth guard, shared loading/empty/error
states, web test baseline, one Many page end to end.

**4C. Client pages.** All WhatsApp pages, Facebook campaigns, accounts (the Instagram section is
staff-only), the public opt-in page.

**4D. Staff pages.** Overview, Instagram accounts and campaigns, campaign stats, leads, logs,
messages, conversations (non-delegated channels only).

**4E. Identity screens.** Team, invitations, password reset, MFA, sessions.

**4F. Close.** Deny the public exchange at the edge (update `e2e/phase2/check_nginx.py` and
`scripts/test_unified_nginx.py`), screenshots, old-tab checklist, full gates.

## 7. Old tabs (starting point for the inventory)

Endpoints seen in the page and its components; step 1 completes and verifies this list.

| Many page | Main endpoints | Audience | Step |
|---|---|---|---|
| `/login` | `/auth/login` | replaced by the SaaS login | 4B |
| `/overview` | `/stats/overview`, `/logs` | staff | 4D |
| `/accounts` | `/instagram/accounts`, `/facebook/*`, `/whatsapp/*`, `/meta/connect/*` | client; Instagram section staff | 4C |
| `/whatsapp` and its campaigns, new, detail, contacts, health, templates pages | `/whatsapp/*` | client | 4C |
| `/facebook-campaigns` | `/facebook/campaigns`, `/facebook/accounts` | client | 4C |
| `/campaigns`, `/campaigns/new`, `/campaigns/[id]`, `/campaigns/[id]/stats` | `/campaigns*`, `/instagram/accounts*`, `/messages/{id}/retry` | staff | 4D |
| `/leads` | `/leads`, `/campaigns`, `/instagram/accounts` | staff | 4D |
| `/conversations` | `/conversations*` | staff, non-delegated channels | 4D |
| `/messages` | `/messages*`, `/campaigns`, `/leads` | staff (P5) | 4D |
| `/logs` | `/logs`, `/campaigns` | staff | 4D |
| `/privacy`, `/terms` | none | public (P6) | 4C |
| `/opt-in/[token]` | public WhatsApp opt-in | public | 4C |

SaaS pages that stay: login, register, accept-invite, account; organization overview, analytics,
bots (overview, knowledge, playground, settings, install, conversations), contacts,
conversations, inbox, settings (data, members, requests); platform pages (bots, change requests,
channels, clients, members, operations); widget pages; privacy and terms.

## 8. Exit criteria

- [ ] Every old tab has a place (checklist with desktop and mobile screenshots in
      `docs/ui-screenshots/`).
- [ ] One login reaches every page the role allows; forbidden cases tested for every role and
      every proxied path; tenant A/B isolation tests pass.
- [ ] Playwright smoke test per page passes; typecheck, lint and build pass.
- [ ] With all flags off both apps behave as today (proven by tests).
- [ ] Both backend suites, script tests, policy and contract copy checks, frozen Instagram check
      and `scripts/dev-up.sh test` pass.

## 9. Testing

GitHub Actions is paused: all gates run locally in WSL Ubuntu with Docker, throwaway databases
only, `APP_ENV=test` and `TEST_DATABASE_URL` set explicitly, host and database name printed
before every run.

Previous harness (outside the repo, check it still exists): WSL `~/phase3/bin/p3repo.sh`,
containers `phase3-pg15` / `phase3-pg17`, databases `many_test_r1` and `saas_p2_full_test`.

Baseline on `main` (2026-11-26, `docs/PHASE-3-REVIEW.md`): SaaS 1491 passed, Many 1286 passed,
script tests 50 passed, `scripts/dev-up.sh test` six cases PASS and nginx 75/75. Web and
dashboard lint, typecheck and build were not part of that run.

Alembic heads (read from the files, 2026-11-26): Many `0031_sso_link`, SaaS
`0035_invitation_locations`.

Cloud sessions (cloned from GitHub): the WSL harness, its containers and any local `.env` file
are not there. Check at the start which of Docker, Python 3.12, Node and the dependencies are
available. Step 1 needs none of them. A gate that cannot run is reported as not run, and a step
is not marked done on gates that were not run.

## 10. How to keep this plan current

At the end of every Phase 4 session, in the same branch as the work:

1. Update the status table (section 1), "Last updated" and the base commit.
2. Record each owner decision in section 4 with its date.
3. Mark gaps confirmed, fixed or disproved in section 5, naming the test.
4. Tick exit criteria only with the command and result that prove them.
5. Add a line to the change log below and update `docs/MERGE-PROGRESS.md`.

## 11. Change log

- 2026-11-26, Claude Code: plan written after the Phase 3 merge, from the merge plan, the
  identity design, the Phase 3 review and a read of both frontends. No tests run, no code changed.
