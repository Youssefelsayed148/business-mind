# Phase 4 plan: one dashboard

Living plan. Last updated: 2026-11-26 (Claude Code, step 1). Base: `main` at `32d32e9`.
Parent: `docs/MERGE-PLAN.md` (Phase 4). Progress record: `docs/MERGE-PROGRESS.md`.

**Status: step 1 approved with P1 to P8 as recommended (2026-11-26); 4A implemented and waiting for the owner's review (same branch and draft PR #12; see section 13). 4B is not started. No Phase 4 code
exists.** `docs/UI-INVENTORY.md` is the inventory; section 12 below is the design. Everything
after step 1 is a proposal until the owner approves P1 to P8.

## 1. Status

Status values: not started / in progress / in review / done / blocked.

| Step | Branch (suggested) | PR | Status | Done when |
|---|---|---|---|---|
| 1. Inventory and design | `claude/blissful-allen-b63jty` (stacked on `docs/phase-4-plan`) | [#12](https://github.com/Youssefelsayed148/business-mind/pull/12) | done (owner accepted P1 to P8, 2026-11-26; PR still open) | Owner approves the docs and P1 to P8 |
| 4A. Connection | `claude/blissful-allen-b63jty` (the session's assigned branch; no separate `phase-4/connection`) | [#12](https://github.com/Youssefelsayed148/business-mind/pull/12) | in review | Role and tenant isolation tests pass |
| 4B. Shell | `claude/blissful-allen-b63jty` (same session branch) | [#12](https://github.com/Youssefelsayed148/business-mind/pull/12) | in review | One Many page works end to end |
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
| P1 | Where does the server-side proxy to Many live: SaaS API or a Next route handler? | SaaS API: reuses session, CSRF, revocation and audit; strict path allowlist; the Many token never reaches the browser. Note that `next.config.ts` already rewrites `/api/*` to the SaaS API | accepted as recommended, 2026-11-26 |
| P2 | How do staff reach WhatsApp and Facebook? (gap 1) | Staff pick an organization and get an SSO membership for its mapped workspace | accepted as recommended, 2026-11-26 |
| P3 | Styling of ported pages | Rebuild with SaaS components and `tokens.css`; no Tailwind | accepted as recommended, 2026-11-26 |
| P4 | Language | English interface, correct RTL/bidi for content, logical CSS properties; Arabic interface later | accepted as recommended, 2026-11-26 |
| P5 | The Many Messages tab (gap 5) | Keep, staff-only | accepted as recommended, 2026-11-26 |
| P6 | Legal and opt-in pages | Keep every existing URL working; the owner chooses the legal text | accepted as recommended, 2026-11-26 |
| P7 | Which `PHASE-3-REVIEW.md` open items are fixed in 4A? | Items 1 (reused MFA code race), 3 (location-limited Admin changes retention and change requests), 7 (Admin replaces a pending Owner invitation); agency replies (item 4) later. Step 1 states which of the others block enabling a flag | accepted as recommended, 2026-11-26 |
| P8 | When is the old Many dashboard retired? | Keep it running until the owner approves parity; removal belongs to cutover | accepted as recommended, 2026-11-26 |

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
| 9 | The SaaS web app only knows `admin`, `editor` and `viewer`: `/auth/me` memberships are typed to those three (`modules/saas/apps/api/app/auth/schemas.py`, `lib/api.ts`). Owner and Manager (stored `org_role`) are not visible to the browser, but the WhatsApp pages depend on them. `GET /tenants/{id}/summary` (flag on) returns the caller's effective role | `auth/schemas.py`, `tenants/router.py` | 4A |
| 10 | The unified nginx config has no location for `/whatsapp/`, `/facebook/`, `/conversations`, `/workspaces/` or `/privacy/` on the Many host, so the old dashboard built for the unified compose may not reach those API paths (read only, not tested). See `UI-INVENTORY.md` fact 5 | `nginx/unified.conf` | confirm in 4A; supports P1 |
| 11 | WhatsApp read pages need workspace Owner or Admin; Manager, Agent and Viewer get 403 on contacts, templates, campaigns and health. The menu must hide them | `routes_whatsapp_outreach.py` | 4C |
| 12 | Old Facebook pages check the global role for actions while the backend checks the workspace role; copied as is, they would hide actions from a client Owner (their global role is `viewer`) | `dashboard/app/(dashboard)/facebook-campaigns/page.tsx`, design 5.4 | 4C |
| 13 | The Next 16 docs named in `modules/saas/apps/web/AGENTS.md` are not in `node_modules/next/dist/docs/` after `npm ci` (Next 16.4.3). They must be found before 4B | `modules/saas/apps/web/AGENTS.md` | 4B |


### 5.1 Gap status after 4A (2026-11-26)

| # | Status | Evidence |
|---|---|---|
| 1 staff membership | fixed | A staff assertion may name an organization and workspace; Many gives an admin SSO membership. Tests `test_staff_for_a_workspace_*` (Many), `test_staff_scope_*` (SaaS); they failed to import before the change |
| 2 mapping writer | fixed | `identity_migrate.py map-report`, `map-apply`, `verify-mapping`; 7 tests that failed first |
| 3 one membership at a time | fixed (design change, see 13) | SSO memberships now live 15 minutes after their last exchange; `test_a_recent_membership_survives_a_move_and_an_aged_one_is_removed` |
| 4 Manager lacks Many permissions | confirmed, handled in the proxy | the allowlist permission for every route equals Many's own guard per role (`scripts/test_many_proxy_allowlist.py`); pages in 4C must still hide actions |
| 5 Messages tab | decided (P5) | kept, staff only: `GET /messages*` in the staff allowlist |
| 6 Instagram OAuth return address | open | 4C and 4D |
| 7 identity screens | open | 4E |
| 8 web test baseline | partly done in 4B (Node 22, not 24) | lint, typecheck, build and the full Playwright suite ran green on Node 22 (14); the Node 24 run is still owed |
| 9 role visibility in the web app | fixed in 4B (display only) | `useOrgRole` reads `GET /tenants/{id}/summary` and falls back to the stored role when identity v2 is off; unit tests `phase4b.unit.mjs`; the badge now shows Owner, Admin, Manager, Agent or Viewer |
| 10 nginx paths | open, not testable here | no Docker daemon in the cloud session; with the proxy the new shell does not depend on it; recheck when the old dashboard is run in the unified compose |
| 11 WhatsApp reads need Owner or Admin | confirmed | allowlist cross-check: Manager, Agent and Viewer are refused on every WhatsApp read, in the SaaS proxy and in Many |
| 12 global vs workspace role in ported pages | open | 4C |
| 13 missing Next 16 docs | closed in 4B | docs are in `modules/saas/node_modules/next/dist/docs` once `npm ci` has run in `modules/saas`; notes in 14.3 |

Phase 3 review items (P7): 1 fixed (`test_a_recovery_code_cannot_be_spent_twice_at_once`,
`test_a_totp_code_cannot_be_used_twice_at_once`), 3 fixed (`test_a_location_limited_admin_cannot_use_organization_wide_settings`),
7 fixed (`test_an_admin_cannot_replace_a_pending_privileged_invitation`). Each failed before its fix.
Items 2, 4, 5, 6 stay open; items 8, 9, 10 are operational and still block enabling a flag; item 11 is a deployment note.

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
- 2026-11-26, Claude Code (step 1): read both frontends, the Many route guards, the SaaS shell
  and the identity docs; wrote `docs/UI-INVENTORY.md`; added gaps 9 to 13 and section 12 (design).
  Docs only. `npm ci` was run in `modules/saas` (ignored files only) to look for the Next 16 docs;
  nothing else was installed or run, no test, build, lint or container.

## 12. Design (step 1 proposal, for the owner's review)

Everything here is a proposal. It follows my recommendations for P1 to P8 (section 4) and does
not become a decision until the owner answers. Facts behind it are in `docs/UI-INVENTORY.md`.

### 12.1 Where the plan and the repo differed

The repo wins. Everything else in the plan matched (base commit, both Alembic heads, page
counts, the old tab list, gaps 1, 2 and 6, the `next.config.ts` rewrite).

| Plan said | Repo shows | Effect |
|---|---|---|
| The old page list (section 7) | The 23 Many pages include `/` (redirect), `/whatsapp` (redirect to contacts) and the legal pages in an auth route group; section 7 does not list `/`, the redirect, or that Facebook has no page of its own | Inventory is complete; no new work |
| Gap 8: `format:check` is a SaaS web check | The script lives at the SaaS root (`modules/saas/package.json`), not in `apps/web` | Wording only |
| Not in the plan | Gaps 9 to 13 (role visibility, nginx paths, WhatsApp reads, global vs workspace role, missing Next docs) | New gaps, section 5 |
| P1 note about `next.config.ts` | There is also `proxy.ts`, which guards upload size and the widget CSP on `/api/*` | A new proxy path must keep it working |

### 12.2 Menu tree and naming

One shell, one sidebar, grouped by what the person manages. Labels are short English nouns.
The organization is the top-level context; staff-only groups appear only for platform staff.

Client menu (inside one organization, `/app/[tenant]/...`):

| Group | Items | Visible to | Source |
|---|---|---|---|
| (top) | Overview | all | S8 |
| Conversations | Inbox; History | all | S17, S18 (the one inbox, also for delegated channels) |
| Contacts | Contacts | all | S19 |
| Insights | Insights | all | S9 |
| Channels | Accounts (Facebook and WhatsApp sections) | all read; Owner and Admin change | M4 |
| WhatsApp | Contacts; Templates; Campaigns; Health | Owner, Admin only | M15 to M20 |
| Facebook | Campaigns | all read; Owner, Admin, Manager change | M9 |
| Settings | Team; Request a change; Data and audit; My account and security | Admin and above; account for all | S20 to S22, S5 |

Staff menu (adds, under `/platform/...`, guarded by the existing server-side check):

| Group | Items | Source |
|---|---|---|
| Platform | Organizations; Members; Bots; Change requests; Channels; Operations | S23 to S29 (today's menu) |
| Many (staff) | Overview; Leads; Messages; Logs | M3, M10, M12, M13 |
| Instagram (staff) | Accounts; Campaigns; Conversations | M4 (Instagram part), M5 to M8, M11 |

Rules:
- Instagram is "a channel", as the merge plan says, but its pages are not organization pages:
  Many's Instagram routes do not filter by workspace (design D1/D2), so they live under
  `/platform/instagram/...`, not under an organization. The client Accounts page shows only
  Facebook and WhatsApp; this removes the "hide the Instagram section" trap.
- Conversations: the shell never shows Many's Take Over and Resume bot for a delegated account;
  the SaaS inbox is the place. The staff Instagram Conversations page lists only rows with
  `managed_by_saas = false` and links delegated ones to the inbox.
- A menu item is hidden when the role cannot open it, but the API check is the real gate. Every
  hidden page also has a direct-URL test (4C and 4D).
- Old URLs keep working: `/accounts` (the Instagram OAuth return address), `/opt-in/[token]`,
  `/privacy` and `/terms` stay; the first redirects by session (query kept) to the right new
  place. Other old paths redirect to their new homes, so bookmarks do not break.

Route map (new):

| New route | Old | Notes |
|---|---|---|
| `/app/[tenant]/channels` | `/accounts` | Facebook and WhatsApp |
| `/app/[tenant]/whatsapp/contacts`, `/templates`, `/health`, `/campaigns`, `/campaigns/new`, `/campaigns/[id]` | `/whatsapp/*` | Owner, Admin |
| `/app/[tenant]/facebook/campaigns` | `/facebook-campaigns` | |
| `/platform/many` | `/overview` | staff |
| `/platform/leads`, `/platform/messages`, `/platform/logs` | same names | staff |
| `/platform/instagram/accounts`, `/campaigns`, `/campaigns/new`, `/campaigns/[id]`, `/campaigns/[id]/stats`, `/conversations` | `/accounts` (Instagram), `/campaigns*`, `/conversations` | staff |
| `/opt-in/[token]`, `/privacy`, `/terms` | same | public |

### 12.3 Organization and channel switchers

- **Organization switcher** (header, left): the shell already builds the list from `me.memberships`
  or, for staff, from all organizations (`AppShell`). It stays. Choosing an organization changes
  the `[tenant]` segment and keeps the page when it exists there. Staff land on `/app` to pick.
  Each tab carries its own organization in the URL, so two tabs do not interfere on the browser
  side (the Many-side flip is gap 3; section 12.7 removes it).
- **Channel switcher**: not a global mode. A channel is a menu group (Facebook, WhatsApp,
  Instagram for staff) and a filter chip row on the pages that span channels: Accounts, Inbox,
  Contacts, Insights. The inbox already lists the channel per thread. No page changes its data
  source because a switcher changed; this avoids hidden state.
- A person with one organization and no staff flag never sees a switcher.

### 12.4 Theme

SaaS tokens (`app/tokens.css`, light and dark, per-user saved choice, follows the system by
default) are the only theme. Many's Tailwind palette and dark sidebar are dropped; no Tailwind
is added (P3). Channel names always carry an icon and a text label, never colour alone. Charts
use the existing chart tokens. New CSS lives in screen files like the existing ones and uses
tokens only. Many's `components/ui/*` are rebuilt on SaaS `lib/ui.tsx` (Loading, Notice, Empty,
DataTable, StatusBadge, Dialog, Toast, Tabs, ConfirmAction exist there).

### 12.5 Language and RTL

P4 recommendation: English interface, correct handling of Arabic and mixed content, Arabic
interface later (needs message catalogs, not in this phase).
- `<html lang="en" dir="ltr">` stays. The Cairo font is already Arabic-capable and self-hosted.
- Content from people (contact names, message text, comments, template bodies, campaign names)
  is rendered with `dir="auto"` and `unicode-bidi: isolate`; phone numbers, IDs, URLs and
  numbers are rendered `dir="ltr"` inside such text.
- New and ported CSS uses logical properties only (`margin-inline`, `padding-inline`,
  `inset-inline`, `text-align: start`). 4B adds a small repo check that fails on physical
  left/right properties in new CSS; the existing SaaS screens already show 0 physical and 67
  logical rules in `app/*.css`.
- Tables keep readable column order in both directions; icons that point (arrows, chevrons) flip
  with direction.
- RTL is verified in 4F with an Arabic-content fixture in the screenshots. Not tested now.

### 12.6 Mockup description

Desktop (width at least 1100px): a left sidebar of about 15rem with the product name, grouped
items (section 12.2) and a collapse button; a top bar with the organization switcher, the
command palette (Ctrl K, already there), a theme toggle and a user menu (account, sign out,
sign out everywhere in 4E). The page body is a header (title, one-line purpose, primary action
on the end side) over cards and tables in a container of at most 80rem. Tables show 20 rows with
paging and a filter bar above; a row opens a detail page or a dialog.

Mobile (below 760px): the sidebar becomes the existing drawer, opened from a menu button; the
switcher moves into the drawer's first row; tables become stacked cards showing the first two
columns with a "details" expander (or scroll horizontally with a fixed first column where cards
do not fit, for example campaign stats); action bars stick to the bottom; touch targets are at
least 2.75rem (the existing control height).

Shared states on every ported page: loading (skeleton or `Loading`), empty (one sentence, one
action, role-aware: a Viewer sees no create button), error (plain message, retry, no raw
status codes), forbidden (explains that the role cannot open the page, links home). A 403 from
the API shows the forbidden state, not a toast. A session expiry sends the person to login and
back (the SaaS `session-expired` event already does this).

### 12.7 How the shell reaches Many (P1, P2)

Recommended: **the SaaS API proxies to Many; the browser never calls Many.**

1. The browser calls the SaaS API at `/api/v1/many/...` (the existing same-origin rewrite), with
   its session cookie and CSRF header, and the organization in the path or a header.
2. The SaaS API checks, from its own database: session valid; MFA state; membership or agency
   grant in that organization; the role's permission for this method and path template; for
   staff pages, `is_platform_staff`. It reuses the existing decorators and tests.
3. It mints the assertion server side (the issuing code exists, PR C) and exchanges it with Many
   over the internal network, caches the resulting short Many token per session and
   organization for less than its 10-minute life, and sends the call with `Authorization` and
   `X-Workspace-Id` set by the server. The browser never sees either.
4. The proxy is **deny by default**: an explicit allowlist of method plus path template,
   built from `UI-INVENTORY.md`, and never `/api/saas`, `/saas`, `/webhooks`, `/auth/sso/*`,
   `/meta/compliance/*`. Client sessions may only reach the paths in `client_scope.py`; staff
   sessions the global paths. Every write is audited with user, organization, path.
5. Multipart (CSV import for WhatsApp contacts) is streamed with a size limit; `proxy.ts` keeps
   its 520 MB ceiling; whether Many's import route has its own size limit is not verified.
6. The public opt-in call is the only unauthenticated path: one allowlisted route, rate limited,
   with the old URL kept.
7. Because the proxy sets the workspace per call, one user working in two organizations is
   no longer limited by Many's single SSO membership (gap 3).
8. Staff (P2): a staff assertion for an organization needs a Many membership for its mapped
   workspace. The smallest change is in `backend/app/services/sso_session.py` (not Instagram,
   not frozen): when a staff assertion names a workspace, create an `admin`-role SSO
   membership for it and do not remove the user's other SSO memberships for staff. Tested in
   4A with a failing test first. If the owner prefers not to touch Many, staff keep Many's own
   login for WhatsApp and Facebook pages (not recommended).
9. Open check for 4A: the SaaS API must be allowed to call the Many API host under the
   Phase 2 internal-service policy (`CHANNEL_INTERNAL_ALLOWED_HOSTS`); I have not verified how
   that policy applies to a new caller.

Why not a Next route handler: it would need its own session check, CSRF, revocation and audit,
all of which already exist in the SaaS API (P1). Why not the browser to Many: the token would
live in the browser, and fact 5 of the inventory suggests the unified nginx paths do not match.

Flags: every identity flag stays off by default; with `SSO_ASSERTION_ENABLED` off the proxy
answers like an unknown route and the old Many dashboard and login keep working unchanged.

### 12.8 Rollback

Each step is its own branch and draft PR, and adds routes and screens only. Nothing is removed
or moved: the old Many dashboard keeps running (P8). Rollback of a step is reverting its merge.
The proxy and the staff membership change are behind flags that default off; turning the flag
off restores today's behaviour. The nginx exchange deny (4F) is the one edge change; its
rollback is the previous `unified.conf`.

### 12.9 Changes to the steps

- 4A also gets: a role field for the shell (Owner, Manager, Agent visible; gap 9), a decision
  on the nginx paths (gap 10), and the staff membership change (12.7 item 8).
- 4B gets: the Next 16 docs check (gap 13), the logical-CSS check (12.5), the redirects for old
  URLs, and the baseline of the SaaS web gates on Node 24 (it declares `>=24 <25`; this
  environment has Node 22, so those gates must run elsewhere).
- 4C and 4D get a direct-URL forbidden test per hidden page, and the workspace-role (not global
  role) rule for ported actions (gap 12).
- Step order stays 4A to 4F. Nothing else changes.
- 2026-11-26, Claude Code (4A): owner accepted P1 to P8; implemented 4A on the session branch; section 13 is the record. Gates in section 13.
- 2026-11-26, Claude Code (4B): owner accepted the 4B plan and its four answers; implemented 4B on the session branch; section 14 is the record.

## 13. Step 4A record (2026-11-26)

Branch: `claude/blissful-allen-b63jty` (the session's assigned branch, so there is no separate
`phase-4/connection`; PR #12 now holds step 1 and 4A and targets `docs/phase-4-plan`). Base:
`main` at `32d32e9` plus PR #11. No migration was added (heads stay Many `0031_sso_link`, SaaS
`0035_invitation_locations`). No Instagram file changed (`scripts/check_instagram_frozen.py` OK).
Every new behaviour is behind a flag that defaults off.

### 13.1 What was built

| # | Change | Where | Tests |
|---|---|---|---|
| 1 | Organization to workspace mapping: `map-report`, `map-apply`, `verify-mapping` (dry run first, reviewed hash, typed database names, refuses on conflict, fills only empty pointers) | `scripts/identity_migrate.py` | 7 new in `scripts/test_identity_migrate.py` |
| 2 | Review item 1: MFA code verification takes a row lock, so one TOTP or recovery code cannot be spent twice | `modules/saas/apps/api/app/identity/mfa.py` | 2 race tests (failed first: 2 successes instead of 1) |
| 3 | Review items 3 and 7: retention and change requests need access to every location; an Admin cannot replace a pending Owner or Admin invitation | `app/tenants/router.py`, `app/tenants/changes.py`, `app/identity/team.py` | 5 failing-first tests, 2 control tests |
| 4 | P2 and gap 3 (Many side): a staff assertion may name an organization and workspace; staff get an admin SSO membership there; SSO memberships live 15 minutes after their last exchange | `backend/app/services/sso_assertion.py`, `sso_session.py` | 7 new Many tests; 2 old tests rewritten |
| 5 | P2 (SaaS side): staff assertions carry `org` and `workspace` when the staff user names an active, mapped organization | `app/identity/sso.py` | 2 new tests |
| 6 | P1: the server-side proxy `/api/v1/many/orgs/{tenant}/...` and `/api/v1/many/staff/...`, a 91-entry deny-by-default allowlist, token reuse, failure mapping, audit of writes, hardened response headers | `app/identity/many_proxy.py`, `many_router.py`, `many_routes.py`, `app/core/config.py` | 47 SaaS tests; 4 cross-check tests against Many's real routes (`scripts/test_many_proxy_allowlist.py`) |
| 7 | Compose and example env pass the two new settings (off by default); RUNBOOK-DEV documents the mapping command and the proxy | `docker-compose.unified.yml`, `.env.unified.example`, `docs/RUNBOOK-DEV.md` | `docker compose config` renders; never started |

### 13.2 Deviations from the step 1 design (the owner should know)

- **SSO memberships are no longer replaced at once** (design 5.4 said a later exchange for another
  organization removes the first). They now stay 15 minutes after their last exchange, then the
  next exchange removes them. Reason: with the proxy minting a token per organization, one person
  in two organizations would otherwise lose one when opening the other. The window is longer than
  Many's token (10 minutes) plus skew, so access to a lost organization still ends within about
  the same time as before. Applies to both scopes.
- **The token cache is per user, organization, scope and role, not per session** (12.7 said per
  session). Every request still checks the session, the role and the grant in the SaaS database
  before a cached token is used, so a revoked session or changed role stops access at once.
- **The proxy needs a few settings** (`MANY_PROXY_ENABLED`, `MANY_API_BASE_URL`, three limits) and
  refuses to start without identity v2 and SSO issuing.
- The staff membership role in Many is `admin` for every staff assertion that names a workspace.

### 13.3 Gates (cloud container, Postgres 16, no Docker daemon; observed values)

| Gate | Result |
|---|---|
| Environment | throwaway Postgres 16.15 clusters on unix sockets (`/var/tmp`), Redis on loopback, pgvector 0.6.0 from apt. The real stack is Postgres 15 (Many) and 17 (SaaS); results are not a substitute for the WSL gates |
| Many full suite (`many_test_r1`, socket path `/var/tmp/many-r1-pg`) | 1292 passed, 0 failed, 3 min 8 s (baseline 1286, plus 6 new). A first run with a different socket path failed 2 migration tests that require the `/var/tmp/many-r1-` prefix; with the prefix they pass |
| SaaS full suite | 1539 passed, 10 failed, 37 min. **The same 10 fail on a clean `origin/main` worktree** (embedding readiness 3, hybrid retrieval 4, r19 index 1, RAG evaluation 2): this container's pgvector 0.6.0 has no `hnsw.iterative_scan`. They are not caused by 4A. The proxy response headers were added after this run; the proxy, MFA and review-fix files were re-run: 73 passed |
| Repo script tests | 61 passed, 25 subtests (50 baseline plus 11 new) |
| ruff check, ruff format --check, strict mypy over `app tests alembic` (SaaS) | clean, 343 files formatted, 336 source files |
| `check_instagram_frozen.py`, `check_policy_copies.py`, both contract-copy checks | OK, OK, OK, OK |
| Allowlist cross-check mutation | changing one permission made `scripts/test_many_proxy_allowlist.py` fail for Manager, Agent and Viewer as intended, and it passed again after restoring |

Not run: `scripts/dev-up.sh test` and the nginx edge checks (no Docker daemon), web or dashboard
lint, typecheck, build and Playwright (no frontend file changed and Node 22 is below the
declared Node 24), a load test, a secret scanner (only a manual check of added lines), the proxy
against a real Many process (the tests use a fake Many; the allowlist and permissions were
checked against Many's real route table instead).

### 13.4 Left for later steps

- Gap 9 (role visibility), gap 10 (nginx paths, needs Docker), gaps 6, 7, 8, 12, 13 (see 5.1).
- Review items 2, 4, 5, 6 of the Phase 3 review; items 8, 9, 10 still block enabling any flag.
- No per-request rate limit on the proxy itself (the exchange is limited at the issuer; Many has
  its own limits). Decide in 4B or 4F.
- Closing the public exchange at the edge is 4F.

## 14. Step 4B record (2026-11-26)

Owner decisions on the 4B plan (2026-11-26): go ahead as proposed; the one page is `/platform/many`
(Many overview, staff only); no separate proxy rate limit; stacked on 4A (same branch). For 4C
and 4D the owner said to use subagents if useful: see 14.5.

### 14.1 What was built (all in `modules/saas/apps/web` unless noted)

| # | Change | Where |
|---|---|---|
| 1 | Real organization role for the shell: `orgRoleFromSummary`, `orgRoleFromStored` (same mapping as the API, never escalates), `orgRoleSatisfies`; `useOrgRole` asks `GET /tenants/{id}/summary` and falls back to the stored role on any failure (identity v2 off answers 404). Display only; the API stays the gate | `lib/org-role.ts`, `lib/use-org-role.ts`, `lib/api.ts` (`tenantSummary`) |
| 2 | Menu tree 12.2 as data with `shipped` flags (an unbuilt page is never linked) and `visibleMenu`; the platform sidebar shows the "Many overview" entry | `lib/menu.ts`, `lib/app-header.tsx` |
| 3 | Organization switcher keeps the current page (cut before the first id); a person with one organization and no staff flag sees no switcher | `lib/org-switch.ts`, `lib/app-header.tsx` |
| 4 | Shared page states: loading, empty (role-aware), failed with retry, forbidden, not available, signed out; plain words, never a raw status code | `lib/page-state.tsx` |
| 5 | Many client through the proxy (`manyStaff`, `manyOrg`) and `manyFailureKind` (401 session, 403 forbidden, 404 not available, 502 or 503 or 504 unavailable, else error) | `lib/many.ts` |
| 6 | The one Many page: `/platform/many` reads `GET /api/v1/many/staff/stats/overview`; the existing server-side staff guard of `/platform` refuses non-staff before the page renders | `app/platform/many/page.tsx` |
| 7 | Old Many dashboard URLs (P6): `/overview` goes to `/platform/many`; the other old pages go to `/moved` (query kept, address shown as text, never markup) until 4C and 4D ship them; temporary 307 | `lib/old-urls.ts`, `next.config.ts`, `app/moved/page.tsx` |
| 8 | Logical-CSS check (12.5): fails on physical left/right properties unless the line carries a `physical-ok:` comment; `npm run check:logical-css`, `npm run test:unit` | `scripts/check-logical-css.mjs`, `package.json` |

No API, Many or Instagram file changed; no migration; no flag turned on.

### 14.2 Changes to existing tests (the owner should know)

- `ui-redesign.spec.ts`: the context badge now reads "Admin" (was "admin"), because it shows the real role label.
- `group-a-operator.spec.ts`: "membership switcher" now expects NO switcher for one organization (12.3, accepted) and a switcher with three options for two organizations.
- `group-c-fixtures.ts`: the fake API answers `GET /tenants/{id}/summary` with 404 (identity v2 off). Without it, eight tests that fail on any unmocked call broke, because the shell now makes that one extra call per organization page.

### 14.3 Next 16 notes (gap 13)

Read in `node_modules/next/dist/docs`: `redirects` in `next.config` run before the filesystem and
pass the query string through; `permanent: false` gives 307. `proxy.ts` replaces `middleware.ts`;
this app's proxy matches only `/api/*` and `/widget/frame`, so old URLs are handled in
`next.config.ts`, not in the proxy. Observed: the first `next build` of a session stops with a
notice that Next 16.4.3 is affected by a known security vulnerability and asks for an upgrade; a
second run of the same command builds. The upgrade was not run (see 14.4).

### 14.4 Gates (cloud container, Node 22.23.5, Postgres 16, no Docker daemon; observed)

| Gate | Result |
|---|---|
| `npm run lint` (`--max-warnings 0`), `npm run typecheck`, `npx next build` | clean, clean, built (the build needed a second run, see 14.3) |
| `npm run test:unit` (all `tests/*.unit.mjs`) | 33 passed (9 new). One new test failed first and found a real bug: `orgRoleFromSummary("toString")` returned a value (prototype lookup); fixed with `Object.hasOwn` |
| `npm run check:logical-css` | OK (0 physical rules in `app/**/*.css`) |
| New Playwright spec `phase4b-shell.spec.ts` | 9 passed: staff sees the page; 403, 404 and 502 states; retry recovers; a client cannot open `/platform/many` and no Many call is made; no switcher for one organization; old URLs keep their query; the moved page does not render markup |
| Full web Playwright suite (185 tests) | first run on a wrong database URL: the DB worker refused to start and 14 tests failed by timeout (environment). Second run: 177 passed, 8 failed (the unmocked `/summary` call, fixed in `group-c-fixtures.ts`). Third run: 184 passed, 1 failed (`ui-characterization` "platform operations", a 30 s click timeout, not touched by this step); that spec passed twice on re-run (12 of 12). Not proven to be flaky on a clean base |
| `check_instagram_frozen.py` | OK |

The browser is the container's Chromium 1243 launched through a temporary config (Playwright
1.64 expects 1248, and the repo config rebuilds the app on every run). The temporary file was
deleted. Not run: Node 24, `scripts/dev-up.sh test`, nginx checks, a real Many process behind
`/platform/many` (the browser calls were answered by Playwright), mobile layout of the new page
(no screenshot), Arabic or RTL checks (planned for 4F).

### 14.5 Subagents for 4C and 4D (owner's question)

Recommendation: do not run 4C and 4D in parallel subagents. Both edit the same shared files
(`lib/menu.ts`, `lib/old-urls.ts`, `lib/many.ts`, the proxy allowlist tests); the test harness
(one database, fixed ports) runs one Playwright suite at a time; and each step stops for the
owner's review. Where subagents do help: an independent security and role review of each step's
diff after it is built, and reading one old page while another is ported. 4C comes first, 4D
after its review.

### 14.6 Left for later steps

- Gap 8 on Node 24; gaps 6, 7, 10, 12 (see 5.1); Phase 3 review items 2, 4, 5, 6; items 8 to 10 still block enabling a flag.
- The menu shows only the Many overview; every other entry in `lib/menu.ts` has `shipped: false`.
- The proxy has no rate limit of its own (decided: not now; revisit in 4F with load numbers).
- Next 16.4.3 security notice: the owner decides whether and when to upgrade.
