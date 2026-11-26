# Phase 4 plan: one dashboard

Living plan. Last updated: 2026-11-26 (Claude Code, step 1). Base: `main` at `32d32e9`.
Parent: `docs/MERGE-PLAN.md` (Phase 4). Progress record: `docs/MERGE-PROGRESS.md`.

**Status: step 1 approved with P1 to P8 as recommended (2026-11-26); 4A in progress. No Phase 4 code
exists.** `docs/UI-INVENTORY.md` is the inventory; section 12 below is the design. Everything
after step 1 is a proposal until the owner approves P1 to P8.

## 1. Status

Status values: not started / in progress / in review / done / blocked.

| Step | Branch (suggested) | PR | Status | Done when |
|---|---|---|---|---|
| 1. Inventory and design | `claude/blissful-allen-b63jty` (stacked on `docs/phase-4-plan`) | [#12](https://github.com/Youssefelsayed148/business-mind/pull/12) | done (owner accepted P1 to P8, 2026-11-26; PR still open) | Owner approves the docs and P1 to P8 |
| 4A. Connection | `phase-4/connection` | - | in progress | Role and tenant isolation tests pass |
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
