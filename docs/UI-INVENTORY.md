# UI inventory (Phase 4, step 1)

Date: 2026-11-26. Base: `main` at `32d32e9`. Written by Claude Code from a read of the code.
Part of `docs/PHASE-4-PLAN.md`. Docs only: **nothing here was run or tested.** Every statement
comes from reading files; where a fact could not be read, the row says "not verified".

## 0. How to read this

- "Many" is the old dashboard in `dashboard/` (Next 14.2, React 18, Tailwind 3.4). "SaaS web" is
  `modules/saas/apps/web` (Next 16.4.3, React 19.3, plain CSS with `app/tokens.css`).
- "Who can use it" has two parts: the **backend guard** (what the API enforces; the only real
  gate) and the **UI hint** (what the old page hides). Where they differ, the backend wins and
  the difference is noted.
- Many roles are `owner`, `admin`, `operator`, `viewer`. SaaS roles are `viewer`, `editor`
  (Agent), `admin` plus the stored `org_role` values when `IDENTITY_V2_ENABLED` is on
  (Owner, Admin, Manager, Agent, Viewer). Platform staff is a separate flag.
- "Client" = a person logged in for one organization. "Staff" = platform staff. Client logins
  cannot call any Many route outside `backend/app/core/client_scope.py` (owner decision
  2026-11-26, design D1/D2), so every Many page not in that list starts staff-only.
- "Step" is the Phase 4 step in `docs/PHASE-4-PLAN.md` that ports or builds it.
- Many API paths below are relative to the Many API root. The old dashboard calls the Many API
  directly from the browser at `NEXT_PUBLIC_API_URL`, with the token from `localStorage`.

## 1. Facts that shape the design (all read from code, none tested)

1. **Many pages call the Many API straight from the browser** with a Bearer token in
   `localStorage` (`dashboard/lib/api.ts`, `lib/auth.ts`). The SaaS web app uses a session
   cookie and a same-origin rewrite of `/api/*` to the SaaS API (`next.config.ts`).
2. **The workspace is chosen by the browser.** For `/whatsapp/*`, `/facebook/*`,
   `/meta/connect/start` and Instagram reconnect, the old client sends `X-Workspace-Id`,
   resolved once from `GET /workspaces/me` (the "default" slug, else the first membership).
   Backend routes outside those prefixes are global and ignore the workspace.
3. **WhatsApp reads need Owner or Admin.** In `routes_whatsapp_outreach.py` every list and detail
   (contacts, templates, campaigns, stats, health) requires workspace role owner or admin; only
   the accounts list and the Facebook list routes accept any role. Manager (maps to `operator`),
   Agent and Viewer (map to `viewer`) therefore cannot open WhatsApp contacts, templates,
   campaigns or health at all. The pages must not be offered to them.
4. **Global vs workspace permission in the ported UI.** Old Facebook pages check the global
   `useCan("manage_campaigns")`, while the backend checks the workspace membership
   (`require_workspace_permission`). For a client login the shadow user's global role is
   `viewer` (design 5.4), so a ported page that kept the global check would hide actions from a
   workspace Owner. Ported pages must read the workspace role, not `/auth/me`'s role.
5. **Path clash on the unified Many host (to verify before 4A).** `nginx/unified.conf` sends
   `/instagram/`, `/campaigns/`, `/leads/`, `/messages/`, `/logs/`, `/stats/`, `/auth/`, `/meta/`
   and `/api/` to the Many API, and everything else (`location /`) to the old dashboard. It has
   no location for `/whatsapp/`, `/facebook/`, `/conversations`, `/workspaces/` or `/privacy/`.
   Read alone this suggests the old dashboard built for the unified compose cannot reach those
   API paths, and that `/campaigns/new` is sent to the API rather than the page. Neither was
   tested here. It supports P1: the shell should not call the Many API from the browser.
6. **Staff are not workspace members.** `sync_memberships` creates no membership for staff
   scope, but WhatsApp and Facebook routes require one (gap 1 in the plan). Staff cannot use
   those pages through single sign-on until P2 is solved.
7. **Delegation hides Many's inbox.** `GET /conversations` rows carry `managed_by_saas`; the old
   page hides Take Over and Resume bot for those rows (`conversations/page.tsx`). Delegation
   settings are per account at `/{platform}/accounts/{id}/saas-delegation` (Owner or Admin;
   Instagram: global owner or admin).
8. **Neither app has a translated interface.** The SaaS web ships one Arabic-capable font
   (Cairo) and uses `dir="auto"` in 3 staff pages and `unicode-bidi` in 2 stylesheets. Its CSS
   has no `margin-left` or `padding-left` style rules in the screen files (0 matches) and 67
   logical-property rules, so the SaaS side is already close to RTL-safe. Many uses Tailwind
   physical utilities; its RTL state was not measured.
9. **Instagram OAuth returns to `FRONTEND_URL/accounts`** (`routes_meta.py` lines 89 to 154), and
   the WhatsApp opt-in link is built from `DASHBOARD_BASE_URL` or `APP_BASE_URL`
   (`routes_whatsapp_outreach.py:761`). The new shell must serve both addresses.
10. **The SaaS shell already has a staff guard.** `/platform` calls `requirePlatformStaff`,
    a server-side fetch of `/api/v1/platform/me` (`lib/staff-access.ts`). Tenant pages guard on
    the client with `useSession` and a role helper (`roleSatisfies`).
11. **Test assets.** The SaaS web has 39 Playwright spec files under `tests/` (they need a running
    API and database; none run here). Many's dashboard has no tests of its own.
12. **Bundled Next docs not found.** `modules/saas/apps/web/AGENTS.md` says to read the docs in
    `node_modules/next/dist/docs/`. After `npm ci` here (Next 16.4.3) that folder does not
    exist, so I could not read them. Before 4B, someone must check the Next 16 conventions
    that matter to the shell (route handlers, `proxy.ts`, caching) against real documentation.

## 2. Many dashboard pages (23 `page.tsx` files)

| # | Route (old) | Purpose | API calls (from the page and its components) | Backend guard | UI hint | Audience in new UI | Flag / dependency | New location | Step |
|---|---|---|---|---|---|---|---|---|---|
| M1 | `/` | Redirect to `/overview` | none | none | none | all | none | `/` of the shell | 4B |
| M2 | `/login` | Email and password login; stores the token | `POST /auth/login`, `GET /auth/me`; links to privacy and terms | public | none | replaced by the SaaS login | `SSO_ASSERTION_ENABLED`, `IDENTITY_V2_ENABLED` for the exchange | SaaS `/login` | 4B |
| M3 | `/overview` | Totals, charts and the activity feed | `GET /stats/overview`, `GET /logs?limit=20` | any logged-in user, global | none | staff | none | Staff section: Overview | 4D |
| M4 | `/accounts` | Connect, reconnect, disconnect and delete Instagram, Facebook and WhatsApp accounts; AI settings; SaaS delegation panel | `GET /instagram/accounts`, `GET /facebook/accounts`, `GET /whatsapp/accounts`, `GET /meta/connect/start`, `POST /meta/connect/mock` (dev only), `GET /facebook/connect/start`, `POST /facebook/connect/callback`, `GET /whatsapp/connect/start`, `POST /whatsapp/connect/callback`, `PATCH /{instagram,facebook,whatsapp}/accounts/{id}/ai-settings`, `DELETE` on the three account types (soft and `/hard`), `POST /instagram/accounts/{id}/reconnect`, `GET`, `PATCH` and `POST .../retry-failed` on `/{platform}/accounts/{id}/saas-delegation` | Facebook and WhatsApp: workspace member (list any role; connect and AI settings need `manage_accounts`; hard delete needs `delete_accounts`). Instagram: global (list any user; AI settings `manage_accounts`; disconnect `disconnect_accounts`; reconnect and hard delete workspace-scoped). Delegation: owner or admin | `manage_accounts`, `disconnect_accounts`, `delete_accounts` (global) | Facebook and WhatsApp sections: client (Owner and Admin write; Manager, Agent, Viewer read). Instagram section: staff only | Meta SDK on the new host (owner sets domains at Meta); delegation settings | Channels: Accounts (one page, channel sections) | 4C |
| M5 | `/campaigns` | Instagram comment campaigns: list, filter, activate, pause, archive, delete | `GET /campaigns`, `GET /instagram/accounts`, `POST /campaigns/{id}/{action}`, `DELETE /campaigns/{id}`, `GET /campaigns/{id}/stats` | `GET` any user, global; writes `manage_campaigns`, delete `delete_campaigns` | same two | staff | client scope denies it | Instagram: Campaigns | 4D |
| M6 | `/campaigns/new` | Create a campaign: form, keywords, post picker, simulate, activate | `POST /campaigns`, `PATCH /campaigns/{id}`, `GET /campaigns/{id}`, `POST/DELETE /campaigns/{id}/keywords...`, `POST /campaigns/{id}/activate`, `POST /campaigns/{id}/simulate`, `GET /instagram/accounts`, `GET /instagram/accounts/{id}/media` | `manage_campaigns` | `manage_campaigns` | staff | same | Instagram: Campaigns, new | 4D |
| M7 | `/campaigns/[id]` | Edit a campaign (reuses the form) | `GET /campaigns/{id}` plus the M6 calls | as M6 | as M6 | staff | same | Instagram: Campaigns, detail | 4D |
| M8 | `/campaigns/[id]/stats` | Campaign results and message list with retry | `GET /campaigns/{id}/stats`, `GET /campaigns`, `POST /messages/{id}/retry` | any user; retry needs `retry_messages` | `retry_messages` | staff | same | Instagram: Campaigns, stats | 4D |
| M9 | `/facebook-campaigns` | Facebook comment campaigns: list, edit, delete, form | `GET /facebook/campaigns`, `GET /facebook/accounts`, `POST/PATCH/DELETE /facebook/campaigns...` | workspace member; writes `manage_campaigns`, delete `delete_campaigns` | **global** `manage_campaigns`, `delete_campaigns` (see fact 4) | client (Owner, Admin, Manager write; others read) | none | Facebook: Campaigns | 4C |
| M10 | `/leads` | Lead table with filters | `GET /leads`, `GET /campaigns`, `GET /instagram/accounts` (the CSV export `GET /leads/export.csv` exists in the API but this page does not call it; not verified in components) | any user, global | none | staff | client scope denies it | Staff: Leads | 4D |
| M11 | `/conversations` | Instagram conversation list and thread; Take Over, Resume bot | `GET /conversations`, `GET /conversations/{id}`, `POST /conversations/{id}/take-over`, `POST /conversations/{id}/resume-bot` | reads any user; actions `manage_accounts` | `manage_accounts`; hides actions when `managed_by_saas` | staff, rows with `managed_by_saas = false` only | delegation flag per account | Instagram: Conversations (delegated rows link to the SaaS inbox) | 4D |
| M12 | `/messages` | Outbound message list with retry | `GET /messages`, `GET /campaigns`, `GET /leads`, `POST /messages/{id}/retry` | any user; retry `retry_messages` | `retry_messages` | staff (P5) | client scope denies it | Staff: Messages | 4D |
| M13 | `/logs` | Audit and automation logs, filters, metadata view | `GET /logs?...`, `GET /campaigns` | any user, global | none | staff | client scope denies it | Staff: Logs | 4D |
| M14 | `/whatsapp` | Redirects to the contacts page | none | none | none | client | none | WhatsApp: Contacts | 4C |
| M15 | `/whatsapp/contacts` | Opted-in contacts: list, import CSV, grant and revoke consent | `GET /whatsapp/contacts?...`, `POST /whatsapp/contacts/import`, `POST /whatsapp/contacts/{id}/{grant,revoke}`, `GET /whatsapp/accounts` | read: workspace owner or admin; write: `manage_contacts` (owner, admin) | `manage_contacts` | client: Owner, Admin | none | WhatsApp: Contacts | 4C |
| M16 | `/whatsapp/templates` | Message templates: list, create, edit, submit, sync, test send | `GET/POST /whatsapp/templates`, `PATCH /whatsapp/templates/{id}`, `POST .../submit`, `POST .../test-send`, `POST /whatsapp/accounts/{id}/templates/sync`, `GET /whatsapp/contacts?consent=opted_in`, `POST /whatsapp/contacts/{id}/grant` | read owner or admin; write `manage_templates` | `manage_templates` | client: Owner, Admin | none | WhatsApp: Templates | 4C |
| M17 | `/whatsapp/campaigns` | WhatsApp campaign list | `GET /whatsapp/campaigns?account_id=...`, `GET /whatsapp/templates`, `GET /whatsapp/accounts` | read owner or admin | `run_campaigns` | client: Owner, Admin | none | WhatsApp: Campaigns | 4C |
| M18 | `/whatsapp/campaigns/new` | Create, dry-run and start a campaign | `POST /whatsapp/campaigns`, `POST .../{id}/dry-run`, `POST .../{id}/start`, `GET /whatsapp/templates?...approved`, `GET /whatsapp/contacts?...` | `run_campaigns` | `run_campaigns` | client: Owner, Admin | none | WhatsApp: Campaigns, new | 4C |
| M19 | `/whatsapp/campaigns/[id]` | Campaign detail, stats, pause, resume, cancel | `GET /whatsapp/campaigns/{id}`, `GET .../stats`, `POST .../{pause,resume,cancel}` | read owner or admin; actions `run_campaigns` | `run_campaigns` | client: Owner, Admin | none | WhatsApp: Campaigns, detail | 4C |
| M20 | `/whatsapp/health` | Quality, limits and outreach settings; opt-in link; refresh | `GET /whatsapp/accounts/{id}/outreach-health`, `POST .../health-refresh`, `PATCH .../outreach-settings`, `POST .../opt-in-link` | read owner or admin; refresh `run_campaigns` or `manage_contacts`; settings and link `manage_contacts` | `useWorkspaceAdmin` | client: Owner, Admin | `DASHBOARD_BASE_URL` for the link | WhatsApp: Health | 4C |
| M21 | `/facebook` (none) | Facebook has no page of its own: accounts live in M4, campaigns in M9 | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| M22 | `/privacy`, `/terms` | Public legal pages (also linked from login) | none | public | none | public (P6) | none | `/privacy`, `/terms` (the SaaS already has both; the owner chooses the text) | 4C |
| M23 | `/opt-in/[token]` | Public WhatsApp opt-in confirmation | `POST /public/whatsapp/opt-in/{token}` (no auth) | signed token | none | public | the link base URL setting | `/opt-in/[token]`, same URL kept | 4C |

Shared Many pieces: `components/layout/Sidebar.tsx` (9 menu items), `AuthGate` (reads the token,
calls `/auth/me`), `lib/permissions.tsx` and `lib/workspacePermissions.tsx` (role to action
tables, copies of the backend table), `components/ui/*` (Button, Table, Panel, Badge, EmptyState,
DataState, Skeleton, Field, PageHeader, Avatar, Highlight, LiveStatusDot, PlatformBadge),
`ToastProvider`, `ErrorBoundary`, `app/error.tsx`, `app/not-found.tsx`, `lib/facebookSdk.ts`
(Meta SDK loader), `lib/eventPresentation.tsx`, `lib/logGrouping.ts`. All are rebuilt on the
SaaS components (P3); none is copied.

Count check: 23 `page.tsx` files = M1 to M3, M4, M5 to M8 (4), M9, M10, M11, M12, M13, M14 to M20
(7), the two legal pages, and the opt-in page. M21 is a note, not a file.

## 3. SaaS web pages (36 `page.tsx` files, all stay)

Guards in the "who" column come from the page files and `lib/app-header.tsx`. The API behind
every route also checks permissions; the SaaS role matrix is tested in Phase 3
(`docs/PHASE-3-REVIEW.md`), which is the authority.

| # | Route | Purpose | Main API calls (page file; sub-components in `lib/` call more) | Who (UI) | Step |
|---|---|---|---|---|---|
| S1 | `/` | Landing redirect | none | all | 4B (target of the new home) |
| S2 | `/login` | Login | `login`, `me` | public | 4B, 4E (MFA step) |
| S3 | `/register` | Self-service signup (`auth/config` decides) | `selfServiceSignup` via component | public | stays |
| S4 | `/accept-invite` | Accept an invitation | `acceptInvitation` | public with a link | 4E (new-account path) |
| S5 | `/account` | Own account, change password | `changePassword` | logged in | 4E (add sessions, MFA) |
| S6 | `/privacy`, `/terms` | Legal pages | none | public | 4C (P6) |
| S7 | `/app` | Organization list, create organization | `createTenant` | logged in; create: staff | 4B (organization switcher) |
| S8 | `/app/[tenant]` | Organization overview: readiness, quota, channels, inbox counts | `conversationTimeseries`, `getBotReadiness`, `handoffAnalytics`, `inboxCounts`, `listBots`, `listInbox`, `listRevisions`, `listTenantChannels`, `tenantQuota` | members; some cards staff | stays |
| S9 | `/app/[tenant]/analytics` | Insights | analytics functions via `insights`, RAG panel (staff) | members | stays |
| S10 | `/app/[tenant]/bots` | Bot list | `listBots`, `tenantQuota` | staff for the page (client redirect); admin hint | stays |
| S11 | `/app/[tenant]/bots/[botId]/overview` | Bot overview and analytics | `analyticsSummary`, `Volume`, `TopQuestions`, `Unanswered`, `Leads` | members | stays |
| S12 | `.../bots/[botId]/knowledge` | Knowledge sources, ingestion, jobs, revisions | `listSources`, `uploadSources`, `replaceSource`, `startIngestion`, `publishRevision` and others | operator page for the client today (redirect); D5 widens it to Owner, Admin, Manager | stays (D5 follow-up) |
| S13 | `.../bots/[botId]/playground` | Test chat with the bot | `playgroundTurn`, `playgroundTurnStream`, `ragTraces`, `messageFeedback` | staff | stays |
| S14 | `.../bots/[botId]/settings` | Bot settings and widget theme | `getBot`, `patchBot` | staff | stays |
| S15 | `.../bots/[botId]/install` | Widget install snippet | `getBot` | staff | stays |
| S16 | `.../bots/[botId]/conversations` and `/[conversationId]` | Saved bot conversations | `listConversations`, `deleteConversation`, `getConversation` | members; delete admin | stays |
| S17 | `/app/[tenant]/inbox` and `/inbox/[conversation]` | The inbox: threads, replies, notes, tags | `listInbox`, `getInboxThread`, `sendAgentReply`, `inboxAction`, `addConversationNote`, tags, `markInboxRead`, `resendChannelMessage` | members; reply needs editor | stays; the one inbox for delegated channels |
| S18 | `/app/[tenant]/conversations` | Conversation history | `listInbox`, `deleteConversation` | members; delete admin | stays |
| S19 | `/app/[tenant]/contacts` and `/[contactId]` | Contacts, follow-ups, merge, erase | `listContacts`, `createContact`, `getContact`, `updateContact`, `mergeContact`, `eraseContact`, `createFollowUp`, `cancelFollowUp` | members; edit editor; erase admin | stays |
| S20 | `/app/[tenant]/settings/members` | Team list and invitations (older routes) | `listMembers`, `updateMemberRole`, `removeMember`, `createInvitation`, `resendInvitation`, `revokeInvitation` | admin | 4E (move to the new team API) |
| S21 | `/app/[tenant]/settings/requests` | Change requests to staff | `createChangeRequest`, `listChangeRequests` | admin | stays |
| S22 | `/app/[tenant]/settings/data` | Retention, export, audit, delete data | `getTenant`, `tenantAudit`, `exportTenantData`, `deleteTenantData`, `deletionPreview` | admin | stays |
| S23 | `/platform` | Organizations (staff) | `platformTenants`, `platformCreateOrganization` | staff (server guard) | stays |
| S24 | `/platform/clients/[clientId]` | Organization detail: plan, quota, bots, channels, members | `platformTenantDetail`, `platformAssignPlan`, `platformQuotaOverride`, `platformPauseBot`, `platformUpdateOrganization` | staff | 4A (workspace mapping field) |
| S25 | `/platform/members` and `/[userId]` | Staff user management | `platformUsers`, `platformUser`, `platformCreateUser`, `platformResetPassword`, `platformUserActive` | staff | stays |
| S26 | `/platform/bots` | All bots | `platformBots` | staff | stays |
| S27 | `/platform/change-requests` | Triage change requests | `listChangeRequests`, `triageChangeRequest` | staff | stays |
| S28 | `/platform/channels` | Channel connections | via `staff-channels` | staff | 4A (location field) |
| S29 | `/platform/operations` | Quotas, jobs, audit, analytics | `platformQuotas`, `platformJobHealth`, `platformJobAction`, `platformAnalytics`, `platformAudit` | staff | stays |
| S30 | `/widget/frame`, `/widget/sample` | Embedded chat widget (public frame) and a staff sample page | public widget API | public / staff | stays untouched (CSP rules in `next.config.ts` and `proxy.ts` must not change) |

Count check: `find modules/saas/apps/web/app -name page.tsx` returns 36 files. The rows group
them (for example S16 covers two files and S10 to S15 cover the bot pages). I did not reconcile
the rows to the files one by one; that command is the authority, and 4B must list any file the
rows miss.

## 4. Old tab to new place (the exit checklist)

Every old sidebar item and every old page has a home. Screenshots are added in 4F.

| Old tab | New menu item | Audience | Step | Placed |
|---|---|---|---|---|
| Overview | Staff, Overview | staff | 4D | planned |
| Accounts | Channels, Accounts | client (Instagram section staff) | 4C | planned |
| WhatsApp (contacts, templates, campaigns, health) | WhatsApp, four pages | client Owner, Admin | 4C | planned |
| Campaigns (Instagram) | Instagram, Campaigns | staff | 4D | planned |
| Facebook Campaigns | Facebook, Campaigns | client | 4C | planned |
| Leads | Staff, Leads | staff | 4D | planned |
| Conversations | Instagram, Conversations (non-delegated rows) | staff | 4D | planned |
| Logs | Staff, Logs | staff | 4D | planned |
| Messages | Staff, Messages | staff (P5) | 4D | planned |
| Login | SaaS login | all | 4B | planned |
| Privacy, Terms | existing SaaS pages | public | 4C | planned |
| Opt-in | `/opt-in/[token]` | public | 4C | planned |

## 5. Not verified

- Whether the old pages call any endpoint not found by the pattern search (the search matched
  quoted paths and template strings in all files under `dashboard/app`, `components`, `lib`).
- The role rules for the SaaS pages beyond the UI hints (they are in the Phase 3 tests, which
  were not run here).
- RTL rendering of either app, and Many's accessibility state.
- Whether the SaaS web builds and passes lint or typecheck on Node 22 (it declares Node 24).
