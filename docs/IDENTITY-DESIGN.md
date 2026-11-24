# Identity design (Phase 3, task 2): DRAFT for owner review

Status: DRAFT, docs only. Nothing here is implemented, run or tested. Facts and citations are in `docs/IDENTITY-DISCOVERY.md` (cited below as "Discovery §n" or "Disc. A/B/C" for the route appendices). Base commit: `cc3b9ab`. Date: 2026-11-24.
Binding rules still apply: Instagram receive/dispatch/send code is frozen; contract text and the two policy-module copies do not change; Postgres 15 and 17 stay separate; flag off means identical behavior; all gates are local (Actions is paused, nothing here claims a CI pass).

---

## 0. One-page summary

### Recommended decisions (all inside the model you decided)

| # | Topic | Recommendation |
|---|---|---|
| R1 | Identity owner | SaaS. The code supports it: server-side sessions, CSRF, platform admin, invitations, audit, Postgres rate limits exist there; Many has a stateless 30-minute JWT, a no-op logout, no user API, no invitations, reset or MFA (Discovery §3, §7). |
| R2 | How Many trusts SaaS | A 60-second, single-use, signed **assertion** (JWT, EdDSA/Ed25519, `kid` for rotation, `aud=many-api`, unique `jti`) is exchanged once at Many for a short Many session token (10 minutes, existing HS256 format). Many holds only the public key. Service-to-service stays on the HMAC contract; user tokens never cross between backends. |
| R3 | Where Many changes | One place: `get_current_user` (`backend/app/api/routes_auth.py:19-38`), plus one new route file for the exchange, additive migrations and config. No Instagram handler is edited. |
| R4 | Many users | SaaS `users` is the one user record. Many keeps a **shadow user** (and workspace memberships marked `source='sso'`) created at exchange, so Many's `authz.py` stays unchanged. No runtime email-based linking, ever. |
| R5 | Organization model | Organization = existing SaaS `tenants` row = one Many workspace (1:1, mapped on both sides and checked on both). Agencies and locations are new, additive tables (options and recommendation in §4). |
| R6 | Roles | Built-in: Owner, Admin, Manager, Agent, Viewer (Billing reserved, not shipped). Permissions are named; roles map to permission sets; no custom roles now (§5). Platform staff stay a separate flag, never a client role. |
| R7 | Agencies | Separate `agencies` + `agency_grants` tables; an explicit grant per client organization, per assigned agency user, capped below Owner, visible and revocable by the client Owner/Admin, every use audited (§4.3). |
| R8 | Client user changes | Behind one flag set, off by default. Many's own `/auth/login` stays as the fallback in every state (§9). |
| R9 | Instagram | No handler edit in Phase 3. SSO **client** tokens are denied on every Many route that is not workspace-scoped (including all Instagram routes) by an allowlist in `get_current_user`. Staff tokens and legacy tokens behave as today. |
| R10 | Migration | Additive, reversible Alembic revisions chained on the real heads (Many `0031_sso_link`, SaaS `0032` to `0034`). Dry-run report first. Password hashes carried over only if a compatibility test passes; otherwise set-password links (§7). |

### Decisions I need from you

| # | Decision | Why it blocks | Default if you do not answer |
|---|---|---|---|
| D1 | **Instagram for client users.** Many's Instagram routes never filter by workspace: `GET /instagram/accounts` returns every account to any logged-in user (`backend/app/api/routes_instagram.py:114-121`). Mapping data alone (`workspace_id` already exists, `instagram_account.py:18-20`) gives no isolation. Choose: (a) client users do not see Instagram pages in the unified UI until a later, separately approved, tiny edit adds a workspace filter to 4 read handlers (this is the STOP-and-ask item); or (b) approve that edit now. | Tenant isolation. | (a). No Instagram edit is proposed in this document. |
| D2 | **Which Many files count as frozen.** I treat `routes_instagram.py`, the webhook receive path and the Instagram token tasks as frozen. Are `routes_campaigns.py`, `routes_conversations.py`, `routes_messages.py` frozen too? They have the same no-workspace-filter problem (Discovery §6). | Decides whether client users get those pages in Phase 3 or later. | Treat as frozen; client tokens denied on them. |
| D3 | **Exposure of the exchange endpoint.** (a) Public `POST /auth/sso/exchange` on the Many host so the current Many dashboard can use SSO before Phase 4 (needs new rate limit and edge checks, §2.6). (b) Internal-only, used by the Phase 4 shell server-side; Many's own dashboard keeps its own login until Phase 4. | "One login reaches every page" can only be true in Phase 3 with (a). | (a), flagged, removed when Phase 4 lands. |
| D4 | **Email provider.** Neither app sends email (Discovery §7). Invite-by-email, reset-by-email and set-password links need one. Recommendation: Amazon SES via SMTP, or the provider you already trust; a `Mailer` interface with a console backend is used until then and staff copy one-time links. | Reset and invite UX. | Console backend, staff-delivered links. |
| D5 | **Clients editing knowledge and bots.** Today these 34 SaaS routes are `platform_staff_only` (Disc. B). Recommendation: Owner/Admin/Manager may edit knowledge sources; bot configuration, RAG settings, tone/rules and bot create/delete stay staff-only. | Matches "client owns knowledge bases". | Recommendation applied. |
| D6 | **Roles.** Confirm Owner, Admin, Manager, Agent, Viewer; Billing reserved; no custom roles in this phase. | Matrix and tests. | As recommended. |
| D7 | **Password hashes.** Carry Many hashes into SaaS if the compatibility test passes (no mass email needed), or force set-password links for everyone. | Cutover effort. | Carry over only if the test passes; users in both apps keep the SaaS password. |
| D8 | **Duplicate-email rule.** Many case variants that collapse to one SaaS user (Discovery §10): survivor = the row with the most recent `login_success` in Many's audit log; others deactivated; roles never unioned; owner reviews the report before apply. | Migration correctness. | As recommended. |
| D9 | **MFA and lifetimes.** TOTP mandatory for platform staff immediately and for client Owner/Admin after a 14-day grace; session: clients idle 12 h / absolute 14 d, staff idle 30 min / absolute 12 h; Many session token 10 min. | Security posture vs convenience. | As recommended. |
| D10 | **First platform staff account and Owner assignment.** Who creates the first staff user and who is the first Owner of each existing tenant (the SaaS has no Owner today). | Cutover checklist. | Owner supplies a list; until then Admins keep today's abilities. |

---

## 1. Contradictions with the decided model

Plain statements, with evidence. Nothing here is hidden in the design.

1. **Confirmed, not contradicted: "identity owner = SaaS".** Many's JWT is HS256 with only `sub`, `exp`, `type` (`backend/app/core/security.py:19-28`), loads the user and reads the role from the database on every request (`routes_auth.py:19-38`), has no refresh (`config.py:109` is unused), no revocation (logout is a no-op, `routes_auth.py:103-105`), and has no user, invitation, reset or MFA code (Discovery §1, §7). The SaaS has all of the session, CSRF and staff-admin machinery. Moving identity to the SaaS is the lower-risk direction.
2. **Contradiction: "mapping data only" is not enough for Instagram isolation.** The decided rule says Instagram joins the organization model through mapping data. `instagram_account.workspace_id` is already non-null (`models/instagram_account.py:18-20`), but the Instagram routes do not use it: `list_accounts` is `db.query(InstagramAccount).all()` (`routes_instagram.py:114-121`), and `get_account`, `health`, `media` are `get_current_user` only (Disc. A). The same holds for campaigns, conversations, messages and most dashboard routes (workspace_id counts 0 in `routes_campaigns.py`, `routes_conversations.py`, `routes_messages.py`; Discovery §6). A client user logged in through SSO would see every tenant's Instagram data. Data mapping cannot fix this; only a route change can. Hence R9 and D1/D2.
3. **Contradiction: "clients manage their work (knowledge bases)".** In the SaaS, clients are read-only on knowledge and bots: 34 of 93 tenant routes are `platform_staff_only` (entries across `core/permissions.py:4-100`, Disc. B), enforced by `require_operator` (`core/tenancy.py:52-54`). Needs D5.
4. **Contradiction: roles named in the model do not exist where assumed.** The SaaS has no Owner (`core/tenancy.py:20`). Many has Owner but `manage_users` is defined and used by no route (`authz.py:16`, Disc. A). The Many "operator" and SaaS "editor" are not equivalent (Many operator can manage campaigns; SaaS editor works the inbox and contacts).
5. **Gap: "Many accepts a short-lived assertion instead of its own login" is not a drop-in.** Many's authorization layer works on an ORM `User` row and on `user_workspace_memberships` (`authz.py:49-76,116-122`). An assertion with no Many user row cannot pass through it. The design therefore needs shadow users and memberships written at exchange (R4). It is additive, but it is a real change to Many's data.
6. **Gap: the SaaS cookie cannot be shared with the Many dashboard.** The cookie is host-only (no `domain`, `auth/cookies.py:32-40`; `docs/DEPLOY-OUTLINE.md` decision 3), and Many's dashboard is on another host (`MANY_HOST` vs `SAAS_WEB_HOST`, `nginx/unified.conf:41,132`). A redirect exchange or a server-side shell (Phase 4) is required. Many's dashboard keeps its token in `localStorage` (`dashboard/lib/auth.ts:6-14`), a pre-existing XSS-theft exposure the exchange does not remove until Phase 4.
7. **Gap: "every agency access is audited".** The SaaS audit trail has no login, logout, session or read events (Discovery §8), staff reading client data is not audited, and Many audits only login events (`routes_auth.py:50,63,79`). New audit events are part of the design (§6.8).
8. **Gap: "invite by email".** The SaaS refuses to invite an email that has no account (`tenants/service.py:131-136`) and neither app has an email provider (Discovery §7). Both need new work (D4, §6.1).
9. **Gap: contract replay.** The signed contract has only a 300-second skew check and no nonce (`backend/app/services/saas_signing.py:14,38-60`). The assertion needs its own `jti` replay store; the contract text is not changed.
10. **Gap found in Many's token check.** `get_current_user` never checks the token `type` claim (`routes_auth.py:27-33`). Today only one token type exists, so this is harmless; once a second type exists it matters. The design adds the check inside the same function.
11. **Not found in code, so no conflict:** agency and location concepts exist in neither app (Discovery §6), so both are greenfield. Roles of "Many platform staff" do not exist in Many; a global Many admin is the de-facto staff (Discovery §6).

---

## 2. Single sign-on flow

### 2.1 Overview
1. The user logs in at the SaaS (`POST /api/v1/auth/login`, existing session cookie).
2. Opening a Many page, the browser asks the SaaS for an assertion for one organization (the "acting org"): `POST /api/v1/sso/assertions` (cookie + CSRF) for same-origin callers, or `GET /api/v1/sso/authorize?org=…&state=…&return=…` for the redirect flow used by Many's dashboard before Phase 4 (D3).
3. The SaaS verifies, at mint time and from its own database: session valid, user active, MFA state, active membership (or active agency grant plus assignment) in that org, role, location scope. It signs a 60-second assertion.
4. Many `POST /auth/sso/exchange` verifies the assertion (signature, `kid`, `iss`, `aud`, `exp`, `nbf`, single-use `jti`), checks the org to workspace mapping on its own side, upserts the shadow user and SSO-managed memberships, and returns a Many access token (10 minutes) in the existing JWT format with `type="sso_access"`.
5. The browser uses that token exactly as it uses today's token. Before expiry it repeats step 2 silently. If the SaaS session was revoked, step 3 fails and access ends within one token lifetime.

### 2.2 Assertion contents (JWT, header `alg=EdDSA`, `kid`)

| Claim | Meaning |
|---|---|
| `iss` | `business-mind-saas` (fixed string) |
| `aud` | `many-api` (a SaaS endpoint or the contract never accepts it) |
| `sub` | SaaS user id (UUID) |
| `jti` | random 128-bit, single use |
| `iat`, `nbf`, `exp` | `exp = iat + 60 s`; Many allows 30 s clock skew |
| `email` | lower-cased, informational only; never used to look up or link users |
| `scope` | `staff` or `client` |
| `org`, `workspace` | SaaS tenant id and the mapped Many workspace id (client scope) |
| `role` | organization role (client scope) |
| `locations` | `null` (all) or a list of location ids (client scope) |
| `via_agency` | agency id or `null` |
| `mfa` | boolean, MFA satisfied in this SaaS session |
| `sid` | SHA-256 prefix of the SaaS session id (audit correlation only) |

The assertion is not a cookie and is never sent to the SaaS or used on the contract. In the redirect flow it travels in the URL **fragment** (not sent to servers, not logged), is removed from history by the page immediately, and is useless after one exchange or 60 seconds.

### 2.3 Keys and rotation
- SaaS holds the private key; Many holds only public keys: `SSO_PUBLIC_KEYS` (map `kid` to PEM). Many cannot mint identities, so a Many compromise does not give identity forgery.
- Rotation: (1) add the new public key to Many config, (2) switch the SaaS to the new `kid` for signing, (3) after 2 minutes (twice the lifetime plus skew) remove the old key. No downtime, no assertion invalidated mid-flight. Emergency revocation: remove the `kid` from Many; all outstanding assertions die within 60 s, Many tokens within 10 minutes.
- Key material lives in environment/secret storage only, never in git; `.env.unified.example` gets placeholder names only.
- If the `cryptography` dependency (needed by PyJWT for EdDSA) is not already in Many's constraints (`backend/constraints.txt`, not checked here), fallback is HS256 with a dedicated `SSO_ASSERTION_SECRET` distinct from `JWT_SECRET` and from every contract secret. This weakens R2 (Many could mint) and would be reported before use.

### 2.4 Replay protection
- `jti` is stored in Many Redis with `SET key 1 NX EX 120` before the token is issued. A second presentation is rejected. **Fail closed:** if Redis is unreachable the exchange is refused (the login limiter's fail-open behavior, `rate_limit_service.py:73-75`, must not be copied).
- 60 s lifetime, `aud` binding, `kid` binding, and the fragment delivery limit exposure. The 300 s contract window is unaffected.

### 2.5 The one place that changes in Many
`get_current_user` (`routes_auth.py:19-38`) gains, in this order and all inside the function:
1. Decode as today. If `type == "sso_access"` and `SSO_ASSERTION_ENABLED` is false, reject (covers a flag turned off while tokens are outstanding). Legacy `type == "access"` tokens follow the unchanged path, byte-for-byte the same decisions.
2. For `sso_access` tokens: load the shadow user by `sub`, require `is_active`, and apply the **client-scope guard**: if the token's `scope` is `client`, the matched route path must be in `CLIENT_SCOPED_ROUTE_PREFIXES` (a reviewed constant), otherwise 403. The set is deny-by-default and initially contains only workspace-scoped routes: `/whatsapp/*` (except nothing else), `/facebook/*`, `/workspaces/*`, `/privacy/contact-erasure/*`, `/auth/me`. It does not contain `/instagram/*`, `/campaigns*`, `/conversations*`, `/messages*`, `/leads*`, `/logs`, `/stats*`, `/meta/*` (R9, D1, D2). Routes are matched on the FastAPI route template, not the raw path.
3. `scope == staff`: no guard; behavior equals today's global admin.

`authz.py` and all route handlers stay unchanged. Because every protected route chains to `get_current_user` (Discovery §3), the guard applies to every Instagram-related route listed in Discovery §12 without touching them.

### 2.6 Edge exposure (nginx)
New Many routes: `POST /auth/sso/exchange` (new file `backend/app/api/routes_sso.py`).
- Under D3(a) it is deliberately public through the existing `location /auth/` (`nginx/unified.conf:84-86`), on the Many host only. `nginx/unified.conf` (not `default.conf`) gains `location = /auth/sso/exchange` with a dedicated `limit_req` zone (default.conf stays untouched). Extended edge checks in `e2e/phase2/check_nginx.py`:
  - exchange with no body on the Many host: app 4xx JSON, no edge-deny header; with the flag off: app 404;
  - same path on `saas.localhost` and `saas-api.localhost`: not routed to Many (404 from Next or the SaaS API, not 2xx);
  - mixed-case and `//`, `%2f`, `/../` spellings of `/auth/sso/exchange` behave identically (regex twin location, like the existing signed-route denies);
  - the signed routes remain denied (existing 48 checks must still pass).
- Under D3(b) the same path is denied at the edge on every host (`^~` plus `~*` twin) and reached only over the internal network.
- SaaS side: `/api/v1/sso/*` is cookie-authenticated, CSRF-checked for POST, and lives on the SaaS API/web hosts like every other `/api/v1/*` route; no new deny is needed, no `/api/channels/*` path is touched.

---

## 3. Single user record and email matching

### 3.1 Record
SaaS `users` is the canonical identity (id, normalized email, password hash, status). Additions (SaaS migration `0033`, §8): `display_name`, `locale`, `mfa_enrolled_at`, `failed_login_count` and `locked_until` (or the Postgres-counter variant, §6.6), `legacy_many_user_id`, `last_login_at`. Many `users` becomes a **linked shadow**: `sso_subject` (SaaS user id, unique, nullable), `auth_source` (`local` | `sso`). A shadow row has an unusable password hash and cannot log in through `/auth/login`.

### 3.2 Normalization and matching rules
- Normalize: trim, Unicode NFKC, lower-case; IDNA-encode the domain. **Do not** strip dots or `+tags` (that would merge different people).
- Match key = the normalized string, exactly. SaaS already stores CITEXT (`db/models/core.py:41`); Many does not (case-sensitive `String`, `models/user.py:17`), so the Many side is compared after normalization in the migration tool only.
- **Linking happens only in the offline, owner-reviewed migration run (§7). The running system never links two accounts by email**, because neither app verifies email ownership (accounts are created by staff). At runtime the shadow row is created from a SaaS-authenticated `sub`, never from an email.
- Duplicates: see §7.3 and D8. Two Many rows that normalize to one email are a conflict reported to the owner; nothing is merged automatically.

---

## 4. Organization, agency and location data model

All new tables are additive. Foreign keys point only inside one database; cross-database links are plain UUID columns checked at the edges (R5).

### 4.1 Organization and the mapping to Many workspaces
Recommendation: **the organization is the existing SaaS `tenants` row** (the platform UI already calls it an organization, `platform/users.py:62-100`); no rename of the table.
- SaaS: `tenants.many_workspace_id uuid null unique`, authoritative.
- Many: `workspaces.saas_tenant_id uuid null unique`.
- Both must agree. The SaaS puts both ids in the assertion; Many refuses the exchange unless `workspaces.saas_tenant_id == org` for `workspace`. A wrong mapping on one side only is a hard failure (confused-deputy guard, §10).
- Set once per organization by a staff-run mapping command (dry run first). Channel accounts (WhatsApp, Facebook, **Instagram**) already carry `workspace_id` (Disc. A, Discovery §6); joining them to the organization is setting that column, i.e. data only.
- The existing `ChannelConnection` link (`db/models/channels.py:28-47`) keeps working unchanged; consistency check: a connection's tenant must equal the tenant mapped to the channel's workspace (read-only report in the migration tool).

### 4.2 Location / brand: options
| | L1: `locations` table + `location_id` on rows | L2: location = child organization | L3: free-text tag on rows |
|---|---|---|---|
| Idea | `locations(id, organization_id, name, status)`; nullable `location_id` on channel connections, contacts, knowledge sources; per-member scope list | a tenant with a parent tenant | a label string, filter by label |
| Isolation | One extra predicate, enforced in one service helper | Every tenant query and quota reasons about a tree; large refactor | Typos create leaks; no integrity |
| Cost | Medium: 1 table, 1 join table, columns, helper | High | Low, unsafe |
| Many side | mapping table only (no change to Instagram tables) | n/a | n/a |
**Recommendation: L1.**

L1 details:
- `locations(id, tenant_id, name, status, created_at)`; `membership_locations(membership_id, location_id)`; `memberships.location_scope` = `all` (default) | `limited`.
- `location_id` (nullable = organization-wide) on `channel_connections`, `contacts`, `knowledge sources`. Conversations take the location of their channel connection; contacts take it from their first conversation channel at creation.
- Rule (fail closed): a **limited** member sees only rows whose `location_id` is in their list; organization-wide rows (`NULL`) are visible only to `all`-scope members. A `limited` member who is also assigned to an agency grant is limited by the narrower of the two.
- Many side (R5): table `channel_location_map(platform, channel_ref, workspace_id, saas_location_id)`; no column is added to `instagram_account`, `whatsapp_account` or `facebook_page`. In Phase 3, `limited` members get **no** access to Many workspace routes (their assertion fails the exchange for Many) until per-route location filters ship in a later phase; location scoping is fully enforced in the SaaS routes (inbox, contacts, knowledge, analytics, channels). This is the safe choice because applying location filters to Many routes means editing WhatsApp/Facebook handlers, and Instagram has none (D1).

### 4.3 Agency: options
| | A1: agency is a tenant with grant rows | A2: separate `agencies` + `agency_memberships` + `agency_grants` | A3: per-user guest memberships (no agency object) |
|---|---|---|---|
| Idea | agency = `tenants` row with `kind='agency'` | agency is its own entity, never a tenant | each agency person is invited into each client with `via_agency` flag |
| Isolation | An agency "tenant" could accidentally own channels, quotas, bots | An agency cannot own client data by construction | Same as A2 for data |
| Control by client | Revoke a grant | Revoke a grant (one row) | Remove each person individually |
| Control by agency | Central | Central: agency admin assigns which of its people use each grant | None; no agency-level view |
| Audit | `via_agency` on events | `via_agency` on events | `via_agency` on events |
| Cost | Low (reuses tenant tables) | Medium (3 tables) | Low |
**Recommendation: A2.** It makes "never implicit access to all clients" structural: nothing links an agency to a client except an `agency_grants` row.

A2 tables:
- `agencies(id, name, status, created_at)`
- `agency_memberships(agency_id, user_id, role)` with `role` in `agency_admin`, `agency_member`
- `agency_grants(id, agency_id, tenant_id, role_cap, location_ids null, status, expires_at null, granted_by_user_id, granted_at, revoked_by_user_id null, revoked_at null)`, unique `(agency_id, tenant_id)` while active
- `agency_grant_assignees(grant_id, user_id)`: a person can act in a client only if they are assigned to that grant. Default: nobody.
Rules:
- `role_cap` is one of Admin, Manager, Agent, Viewer, **never Owner** and never any team-management or agency-management permission; an agency user's effective role in the client is the grant's cap, not their agency role.
- Only the client's **Owner** creates, changes or revokes a grant (Admins can view). Revocation is immediate in the SaaS; Many access ends at token expiry (at most 10 minutes) and no new assertion can be minted.
- The client sees every grant (agency name, cap, locations, who is assigned, last use) on a "Access granted to others" screen and can revoke it.
- Grants can expire (`expires_at`); expiry is checked at mint time.
- Agency users appear in the client's audit log with the agency name (`via_agency`).
- Platform staff create agencies and agency admins; they cannot create a grant on a client's behalf except through a logged, break-glass staff action that the client Owner can see (default: not allowed).

### 4.4 Where each table lives
SaaS Postgres 17: `locations`, `membership_locations`, agencies tables, MFA, reset tokens, session metadata, role columns. Many Postgres 15: `workspaces.saas_tenant_id`, `users.sso_subject/auth_source`, `user_workspace_memberships.source`, `channel_location_map`. No cross-database foreign key; no shared database.

---

## 5. Roles, permissions and the role matrix

### 5.1 Roles (built-in, with scoping)
- **Owner**: everything in the organization, including agency grants, role changes for Admins, billing and organization settings. At least one Owner per organization (last-owner protection).
- **Admin**: team management for Manager/Agent/Viewer, channels, knowledge, campaigns, exports, audit view, contact erasure. Cannot grant or change Owner, cannot manage agency grants.
- **Manager**: campaigns and templates management, knowledge editing, contacts, inbox, analytics. No team or channel-connection management.
- **Agent**: inbox (take over, reply, resolve, assign, notes, tags), view and edit contacts, follow-ups, analytics read.
- **Viewer**: read-only.
- **Billing**: reserved name, not shipped (no billing exists; plan labels are staff-set, `core.py:84`). Billing permissions are held by Owner for now.
- **Platform staff**: separate flag `is_platform_staff`, never a membership role, never grantable through an agency. In Many, `scope=staff` tokens.
- Custom permission sets: **not now.** A role to permission table in code is cheap and testable; per-organization editable sets add escalation paths (a custom role that quietly includes team management) and a test explosion. Revisit after the built-ins have been used.
- Location scoping is orthogonal: any role can be `limited` to locations (§4.2).

### 5.2 Permission names and matrix
Each route declares one permission string; the code holds one `ROLE_PERMISSIONS` table per app (Many keeps its existing 11 names and gains a mapping).

| Permission | Owner | Admin | Manager | Agent | Viewer | Staff |
|---|---|---|---|---|---|---|
| inbox.read / contacts.read / analytics.read / channels.read | Y | Y | Y | Y | Y | Y |
| inbox.reply (takeover, send, resolve, assign, notes, tags) | Y | Y | Y | Y | - | Y |
| contacts.write (create, edit) | Y | Y | Y | Y | - | Y |
| contacts.delete, contacts.merge, contacts.stages, conversations.delete | Y | Y | - | - | - | Y |
| contacts.export, analytics.export, data.export | Y | Y | - | - | - | Y |
| knowledge.read | Y | Y | Y | Y | Y | Y |
| knowledge.write (sources, ingestion, publish) | Y | Y | Y | - | - | Y |
| bots.configure, rag.settings, bot create/delete | - | - | - | - | - | Y |
| campaigns.read | Y | Y | Y | Y | Y | Y |
| campaigns.manage (create, edit, pause, keywords) | Y | Y | Y | - | - | Y |
| campaigns.run, templates.manage | Y | Y | - | - | - | Y |
| channels.connect (OAuth, reconnect, AI settings, delegation) | Y | Y | - | - | - | Y |
| channels.disconnect, channels.hard_delete | Y | Y (disconnect only) | - | - | - | Y |
| team.read | Y | Y | - | - | - | Y |
| team.manage (invite, role, deactivate for Manager/Agent/Viewer) | Y | Y | - | - | - | Y |
| team.manage_admins (change Admin, grant/revoke Owner) | Y | - | - | - | - | Y |
| agency.view | Y | Y | - | - | - | Y |
| agency.manage (grants, revoke) | Y | - | - | - | - | Y |
| audit.view | Y | Y | - | - | - | Y |
| data.erase (contact erasure) | Y | Y | - | - | - | Y |
| org.settings | Y | Y | - | - | - | Y |
| org.delete / purge | - | - | - | - | - | Y |
| billing.view / billing.manage (reserved) | Y | - | - | - | - | Y |

Notes: the matrix was built to preserve current abilities (SaaS `viewer`, `editor`, `admin` rows in Disc. B; Many `ROLE_PERMISSIONS`, `authz.py:14-46`), except where D5 widens clients on knowledge. "Staff" means platform staff.

### 5.3 Mapping of existing roles (no silent escalation)
| Source | Maps to | Notes |
|---|---|---|
| SaaS viewer | Viewer | exact |
| SaaS editor | Agent | exact for inbox, contacts, follow-ups |
| SaaS admin | Admin | owner promotion is a separate, explicit staff action (D10) |
| Many owner | Owner | |
| Many admin | Admin | |
| Many operator | Manager | Many operator had only `manage_campaigns` + audit; Manager is similar; the dry-run report lists any gain or loss per person |
| Many viewer | Viewer | |
| `users.role` default `admin` | not carried | The global role is mapped per workspace membership; a global role never becomes organization access by itself |
Rule: a migrated person must not end up with a permission they did not have, unless the owner confirms it in the dry-run report.

### 5.4 Role mapping into Many (per exchange)
Organization role to Many workspace role (`roles.py:1-6`): Owner to `owner`, Admin to `admin`, Manager to `operator`, Agent to `viewer`, Viewer to `viewer`. The shadow user's global `users.role` is `viewer` for client scope (so the global-permission routes stay closed even if the client-scope guard were bypassed) and `admin` for staff scope.

### 5.5 Agency grants in the matrix
A grant's `role_cap` is an ordinary role from §5.1 restricted to Admin, Manager, Agent, Viewer, and never includes `team.*`, `agency.*`, `billing.*`, `org.*`. Effective role for an agency person = the cap, further narrowed by the grant's `location_ids` and the person's own agency role (agency_member cannot exceed the grant).

---

## 6. Client team management

### 6.1 Invite by email
- `POST /api/v1/tenants/{id}/invitations` (permission `team.manage`) always answers "If this address can be invited, an email was sent", whether or not an account exists. This removes today's oracle (`tenants/service.py:131-136`). It no longer requires an existing user: acceptance can create the account.
- Token: random 256-bit, only its SHA-256 stored (as today, `auth/security.py:38-40`), 7-day expiry, single use, bound to one email and one role (+ location scope).
- Accept: (a) existing account: login first, session email must match (today's rule, `tenants/service.py:258`); (b) new account: the link opens a set-password page; the token, not an email claim, authorizes creating the account with the invited email.
- Admins cannot invite Owners or Admins (`team.manage_admins`).
- Until D4 is decided, the invite screen shows the one-time link for the inviter to deliver (the console `Mailer` backend).

### 6.2 Assign role, deactivate
- Role changes: new service `change_role` with rules in §10 (no self-edit, no last-Owner removal, no edit above one's own authority).
- "Deactivate" at organization level = membership `status=revoked` (reuses `core.py:117-118`); it also records who and why. Global account disable remains a staff action (`platform/users.py:328`).

### 6.3 Password reset (self-service)
Generic responses everywhere: "If an account exists, an email was sent". Token: random, SHA-256 stored in new `password_reset_tokens`, 30-minute expiry, single use, issued per user, rate-limited per (email, IP) and per email. Link built from a configured base URL, never from the `Host` header. Using it sets the password, revokes **all** sessions (like staff reset, `platform/users.py:312`), and writes an audit event. Staff reset (`platform/users.py:304-315`) stays.

### 6.4 MFA (TOTP)
- RFC 6238 TOTP, 30 s step, 6 digits, one step of drift; secret stored encrypted at rest with a key from the environment (same pattern as channel secrets, `channels.py:37-39`); 10 single-use recovery codes stored hashed.
- Mandatory for platform staff at once and for client Owner/Admin after a 14-day grace (D9). During grace a banner and audit events; after grace login yields an "enroll now" session that can reach only the enrollment endpoints.
- The assertion carries `mfa`; with `SSO_REQUIRE_MFA_FOR_ADMIN` on, Many refuses Owner/Admin/staff exchanges without it (defense in depth).
- MFA reset for a user: by staff only, with audit (and by an Owner for Admin/Manager/Agent/Viewer).

### 6.5 Sessions: lifetime, "log out everywhere"
- New: `sessions.last_seen_at`, `ip_hash`, `user_agent` (nullable) so users can list devices.
- Lifetimes (D9): clients idle 12 h, absolute 14 days (today: absolute 14 days only, `core/config.py:36`); staff idle 30 min, absolute 12 h. Idle timeout is checked in `get_current_user` (SaaS) against `last_seen_at`, updated at most once a minute.
- `POST /api/v1/auth/sessions/revoke-all` (cookie + CSRF): revokes every session of the user (the service method already exists, `auth/service.py:215-220`) and keeps or drops the current one by parameter. Role change, membership revocation, grant revocation and password change also revoke affected sessions (password change already does, `service.py:148-156`).
- Many token lifetime 10 minutes bounds how long a revoked person keeps Many access.

### 6.6 Lockout and rate limits
- Login keeps the per-IP bucket (`auth/router.py:37-52`) and gains: a per-(email, IP) bucket 5 per 15 minutes with a growing delay, and a per-email bucket 20 per hour that only slows (no hard lock), to avoid letting an attacker lock a victim out. Counters are applied identically for unknown emails.
- Unknown emails run a dummy Argon2 verification so response time does not reveal existence (today the short-circuit skips the hash, Discovery §5).
- New limits: reset request, invitation accept, MFA verify (5 per 5 min per user), exchange (Many edge zone plus a per-user limit), assertion mint.
- SaaS counters stay in Postgres (`core/ratelimit.py`), failing closed on database error as today.

### 6.7 Enumeration-safe responses (summary)
Login, reset request, invite and (disabled) register answer identically for existing and unknown emails, in body, status and (approximately) timing. `EMAIL_TAKEN` (`auth/service.py:81-82`) stays unreachable while self-serve is off; if self-serve is ever enabled it must change to the same generic pattern.

### 6.8 Audit log
New events, tenant-visible unless noted, all with `actor`, `org`, `via_agency` when present, request id, no secrets: `auth.login_success`, `auth.login_failed` (staff and org-admin visible), `auth.logout`, `auth.sessions_revoked`, `auth.password_reset_requested/completed`, `auth.mfa_enrolled/failed/reset`, `team.invited/accepted/role_changed/deactivated`, `agency.grant_created/changed/revoked/used` (first use per session), `sso.assertion_minted` (SaaS), `sso.exchange_succeeded/failed` (Many audit log, new action names), `staff.tenant_entered` (rate-limited, staff-visible and client-visible). Many's existing audit table is reused (`audit_service.py:16`).

---

## 7. Migration of existing users

### 7.1 Principles
No production data is touched in this phase. The migration tool runs first against restored copies on staging (Phase 7 rehearsal), always dry-run first, always idempotent, always preceded by a backup, always with an advisory lock.

### 7.2 Steps
1. **Inventory (read-only):** for each app list normalized email, active flag, role(s), memberships, and the **hash parameters only** (the `$argon2id$v=…$m=…,t=…,p=…` prefix; never the hash).
2. **Match report:** group by normalized email; classes: Many-only, SaaS-only, both, Many-duplicates (case variants), role conflicts, inactive on one side.
3. **Owner review** of the report, including role changes (§5.3), Owner assignment per organization (D10) and duplicate survivors (D8). Nothing applies without the reviewed report's hash.
4. **Apply:** create missing SaaS users, memberships and the org to workspace mapping; write Many shadow rows and `sso_subject` links; never overwrite an existing SaaS password.
5. **Verify:** counts, that every Many user is either linked or deactivated by decision, and that no user gained a permission beyond the report.
6. **Cutover per organization** by flag (§9): staff first, then one pilot organization.

### 7.3 Passwords
- Both apps store Argon2 strings (Discovery §2). **Not tested here:** whether passlib's output verifies under argon2-cffi's `PasswordHasher` and the reverse. The implementation session runs that test on synthetic hashes first (passlib-generated hash verified by argon2-cffi; `check_needs_rehash` after success).
- If it passes: Many-only users keep their password through a carried hash, rehashed at next login. Users present in both apps keep the **SaaS** password; their Many hash is discarded.
- If it fails or a user's parameters are unsupported: that user gets a one-time **set-password link** at cutover (staff-delivered until D4), the old hash is not carried, and their old Many password stops working.
- Everyone's Many access via SSO still requires SaaS login, so carried hashes only help for the SaaS login itself.

### 7.4 Duplicates (read-only SQL for the owner, not run)
Many (Postgres 15):
```sql
SELECT lower(btrim(email)) AS norm, count(*) AS n, array_agg(id) AS ids
FROM users GROUP BY 1 HAVING count(*) > 1;
```
Cross-app counts need the two exports joined offline on the normalized email; there is deliberately no cross-database query.

---

## 8. Reversible migrations and rollback

### 8.1 Alembic revisions (chained on the verified heads; Discovery §0)
SaaS (`modules/saas/apps/api/alembic/versions/`, head `0031_contact_erasure`):
- `0032_identity_orgs` (down `0031_contact_erasure`): `locations`, `membership_locations`, `memberships.location_scope`, `memberships.org_role` (nullable, new role strings), `agencies`, `agency_memberships`, `agency_grants`, `agency_grant_assignees`, `tenants.many_workspace_id`, nullable `location_id` on channel connections, contacts, knowledge sources.
- `0033_auth_security` (down `0032`): user columns (§3.1), `user_mfa`, `user_recovery_codes`, `password_reset_tokens`, `sessions` metadata columns, invitation columns (location scope, new-account flag).
- `0034_roles_backfill` (down `0033`): data only. Fills `memberships.org_role` from the mapping (viewer to viewer, editor to agent, admin to admin). The legacy `role` column stays and is dual-written while the flag exists, so rollback needs no data reconstruction.
Many (`backend/alembic/versions/`, head `0030_meta_account_erasure`):
- `0031_sso_link` (down `0030_meta_account_erasure`): `users.sso_subject` (unique, nullable), `users.auth_source` (default `local`), `user_workspace_memberships.source` (default `local`), `workspaces.saas_tenant_id` (unique, nullable), `channel_location_map`.
No existing column type changes, no table is rewritten, no Instagram table is altered. Every `upgrade()` has a `downgrade()` that drops exactly what was added, in reverse order. Tests (§12): upgrade to head, downgrade one step at a time to the previous head, upgrade again (up, down, up) on a throwaway database; plus a data test that a downgrade after the backfill leaves the legacy columns intact.

### 8.2 Rollback ladder
1. Flip the flag(s) off (seconds). Many's own login works as before; SSO tokens are rejected; SaaS keeps its current roles (legacy `role` column still authoritative while `IDENTITY_V2_ENABLED=false`).
2. Revoke the public key in Many (`SSO_PUBLIC_KEYS` empty): all exchanges refused.
3. Downgrade Many `0031_sso_link`, then SaaS `0034` to `0032`, only after a fresh backup. Shadow users are harmless leftovers if left in place (unusable password, `auth_source='sso'`).
4. Full restore from backup per `docs/backup-and-restore.md` for a worst case.

---

## 9. Flags and the fallback

| Flag | App | Default | Effect when off |
|---|---|---|---|
| `SSO_ISSUER_ENABLED` | SaaS | false | `/api/v1/sso/*` returns 404; no assertions minted |
| `SSO_ASSERTION_ENABLED` | Many | false | `/auth/sso/exchange` returns 404; `sso_access` tokens rejected in `get_current_user` |
| `IDENTITY_V2_ENABLED` | SaaS | false | roles, locations, agencies, invitation changes, audit additions inactive; `memberships.role` stays authoritative |
| `MFA_ENFORCE_STAFF`, `MFA_ENFORCE_ADMINS` | SaaS | false | MFA optional |
| `SSO_REQUIRE_MFA_FOR_ADMIN` | Many | false | exchange does not check `mfa` |
Flag-off equals today: no new route answers, no new column is read, legacy tokens and cookies follow the unchanged code paths (R3). **Many's own `/auth/login` and JWT stay as the fallback in every state**, including as the break-glass path for staff; any later restriction of it is a separate Phase 7 decision.

---

## 10. Threat model

| Threat | Scenario | Control | Test |
|---|---|---|---|
| Cross-tenant read through Many global routes | Client user calls `GET /instagram/accounts` or `/campaigns` | Client-scope allowlist in `get_current_user` (§2.5); default deny | T-ISO-1..n |
| IDOR on ids | Client A guesses a tenant, bot, conversation, contact or workspace id of client B | SaaS: tenant dependency, hidden tenants return 404 (`core/tenancy.py:68-82`), all service queries by `tenant_id`; Many: workspace membership required (`authz.py:116-128`) plus per-route workspace filters on WhatsApp/Facebook | T-IDOR |
| Confused deputy across agency grants | Agency person acts in client A using a grant meant for client B, or uses a grant they are not assigned to | Grant checked at mint from SaaS DB (agency, tenant, assignee, expiry, status); assertion carries org and workspace; Many verifies the workspace to tenant map; resource checks use the grant cap, not the agency role | T-AGY |
| Agency access not removable | Client revokes but access continues | Revocation immediate in SaaS; Many access ends in at most 10 minutes; no new mint | T-AGY-REV |
| Assertion replay | Captured assertion reused | `jti` single use in Redis (fail closed), 60 s, `aud`, `kid`; fragment delivery; never logged | T-REPLAY |
| Assertion forgery | Compromised Many mints identities | Asymmetric key: Many holds public key only | key test |
| Key compromise | Private key leaked | `kid` rotation (§2.3), revoke by removing the key, short lifetimes | rotation test |
| Privilege escalation by role edits | Admin grants themselves Owner, edits an Owner, removes the last Owner, or an agency raises its cap | Permission `team.manage_admins` Owner-only; no self role edit; last-Owner protection; cap < Owner; every change audited and revokes the target's sessions | T-ESC |
| Role change not applied | Role lowered but old session keeps power | SaaS reads the role from the database per request; Many token ≤ 10 min and re-mapped at each exchange | T-ROLE-LAG |
| Email-match account takeover | Attacker registers a victim's email in one app and gets linked | No runtime email linking; linking only in the reviewed offline run | design test |
| Invitation hijack | Token intercepted or sent to the wrong person | Token bound to one email; set-password path is token-authorized; 7-day expiry; single use; resend rotates the token; generic responses | T-INV |
| Reset poisoning | Host header forged to build a reset link | Link from configured base URL only | T-RESET |
| Account enumeration and timing | Login, reset or invite reveals existence | Generic bodies and codes; dummy hash for unknown email (§6.6) | T-ENUM |
| Lockout DoS | Attacker locks a victim | Slow-down per email, hard thresholds only per (email, IP) | T-LOCK |
| CSRF on mint and revoke-all | Cross-site request mints or revokes | Cookie + `X-CSRF-Token` on all POSTs (`auth/cookies.py:71-80`); `GET authorize` has no side effect except a redirect with a fresh assertion and checks `state` | T-CSRF |
| Open redirect | `return` points to an attacker host | `return` must match an exact allowlist of Many dashboard origins | T-REDIR |
| XSS token theft | Script reads Many's `localStorage` token | Pre-existing; 10-minute lifetime and short exchange limit blast radius; Phase 4 shell removes the browser-held token | noted |
| Stolen staff session | Staff cookie used for support-level access | Mandatory MFA, idle 30 min, absolute 12 h, `staff.tenant_entered` audit, no impersonation | T-STAFF |
| Edge exposure of new route | Exchange reachable where it should not be | Extended `check_nginx.py` (§2.6) incl. mixed-case spellings | edge checks |
| Frozen Instagram code edited | Any task needs it | STOP-and-ask; test that Instagram files are byte-identical to `origin/main` | T-FROZEN |
| Contract tampering | Contract text or policy copies change | `scripts/check_contract_copies.py` and `scripts/check_policy_copies.py` stay green | existing |

---

## 11. Implementation plan (later session on the owner's machine, after approval)

Small commits, each with tests and the local gates. Branch `phase-3/identity-impl` from `main`. Paths below are exact; names of new test files are proposals.

**Many**
1. `backend/app/core/config.py`: add `SSO_ASSERTION_ENABLED` (default false), `SSO_PUBLIC_KEYS`, `SSO_ISSUER`, `SSO_AUDIENCE`, `SSO_REQUIRE_MFA_FOR_ADMIN`, `SSO_TOKEN_MINUTES`. Test `backend/tests/test_sso_config.py` (defaults, invalid values fail startup).
2. `backend/alembic/versions/0031_sso_link.py` plus model edits in `backend/app/models/user.py`, `workspace.py`, `user_workspace_membership.py`, new `backend/app/models/channel_location_map.py`. Test `backend/tests/test_migration_0031.py` (up, down, up).
3. `backend/app/services/sso_assertion.py`: verify, `kid` lookup, claims check, Redis `jti` store (fail closed). Tests with fixed keys: `test_sso_assertion.py` (valid, expired, not-yet-valid, wrong `aud`/`iss`/`kid`, tampered, replay, Redis down).
4. `backend/app/services/sso_session.py`: shadow user upsert, membership sync (`source='sso'`), role mapping (§5.4). Test `test_sso_session.py`.
5. `backend/app/api/routes_sso.py` (new): `POST /auth/sso/exchange`; register in `backend/app/main.py`. Flag off: 404. Test `test_sso_exchange.py`.
6. `backend/app/api/routes_auth.py`: `get_current_user` change (§2.5) and `backend/app/core/client_scope.py` (the allowlist constant). Tests: `test_sso_guard.py` (every route in `app.routes` classified; client-scope allowed only for the allowlist; staff and legacy unchanged), `test_flag_off_identical.py` (legacy token behavior and 401/403 results equal with the flag on and off for every route).
7. `scripts/check_instagram_frozen.py` (new, stdlib only): fails if `git diff origin/main --` over the owner-confirmed Instagram file list is non-empty (list in D2 outcome; candidate list from Discovery §12: `backend/app/api/routes_instagram.py`, `routes_webhooks.py`, `workers/instagram_token_tasks.py`, `workers/instagram_token_beat_schedule.py`, `models/instagram_account.py`).

**SaaS** (`modules/saas/apps/api/`)
8. `alembic/versions/0032_identity_orgs.py`, `0033_auth_security.py`, `0034_roles_backfill.py`; models in `app/db/models/core.py` and new `app/db/models/identity.py`. Test `tests/test_identity_migrations.py` (up, down, up, backfill, legacy columns intact).
9. `app/identity/roles.py` (permission table, §5.2), `app/identity/locations.py`, `app/identity/agency.py`; extend `app/core/tenancy.py` (`TenantContext` gains permission checks, location scope, `via_agency`) and `app/core/permissions.py` (route to permission map). Tests: `tests/test_role_matrix.py` (table-driven over every route in `app.routes` x every role x allowed/forbidden), `test_location_scope.py`, `test_agency_grants.py`.
10. `app/identity/sso.py` and `app/identity/router.py`: key loading, assertion minting, `POST /api/v1/sso/assertions`, `GET /api/v1/sso/authorize`; register in `app/main.py`. Tests: `test_sso_issue.py` (claims, 60 s, MFA flag, revoked or expired grant, non-member, limited scope, state, redirect allowlist).
11. `app/identity/team.py`: invitations v2 (generic response, new-account acceptance), role changes, deactivate, last-Owner protection; edits to `app/tenants/router.py` and `app/tenants/service.py` under `IDENTITY_V2_ENABLED`. Tests `test_team_management.py`, `test_escalation.py`.
12. `app/identity/reset.py`, `app/identity/mfa.py`, `app/auth/service.py` (dummy hash, new buckets, session idle/revoke-all), `app/auth/router.py` (new endpoints), `app/core/audit.py` events. Tests `test_reset.py`, `test_mfa.py`, `test_lockout.py`, `test_enumeration.py`, `test_sessions.py`.
13. `app/identity/mailer.py` (interface, console backend, provider after D4).
14. `scripts/identity_migrate.py` (inventory, report, apply, verify; dry-run default; advisory lock). Tests with synthetic data only: `tests/test_identity_migrate.py`.

**Infra and docs**
15. `nginx/unified.conf` (rate-limit zone and exact location for the exchange, or the deny under D3(b)); extend `e2e/phase2/check_nginx.py` (§2.6); `.env.unified.example` placeholders; `docker-compose.unified.yml` env passthrough. `nginx/default.conf` untouched.
16. `docs/RUNBOOK-DEV.md` (key generation for dev, flag matrix), `docs/DEPLOY-OUTLINE.md` (key custody, MFA bootstrap, first staff, first Owner), `docs/MERGE-PROGRESS.md`.

Order: 1 to 7 and 8 first (independent), then 9, 10, 11, 12, 13, 14, 15, 16. Each commit leaves both suites green and the flags off.

---

## 12. Test plan

Run locally on throwaway databases only: print host and database name, set `APP_ENV=test` and `TEST_DATABASE_URL` explicitly (CLAUDE.md rule 2). Baselines at the start of implementation (flag off): Many 1084 passed, SaaS 1293 passed (verified numbers from the Phase 2b gate; to be re-verified in that session, not here).

| Area | What is tested |
|---|---|
| Role matrix, every route | Table-driven from `app.routes` of each app: for every route and every role (Owner, Admin, Manager, Agent, Viewer, Staff, no auth, other-tenant member), expected allow or forbid; the test fails if a route has no policy entry (extends the SaaS completeness check at `main.py:75-91`; new for Many). Includes Disc. A, B and C rows. |
| Tenant isolation | Two organizations, same data shapes: each role in org A is denied (404/403) on org B's tenants, bots, contacts, conversations, knowledge, channels; Many WhatsApp/Facebook routes by `X-Workspace-Id`; client-scope token denied on every non-allowlisted Many route (incl. all Instagram rows of Discovery §12). |
| Agency grants | Grant create, assign, expire, revoke; unassigned agency person denied; cap never above Admin; no Owner or team/agency permissions; client sees and revokes; audit has both ids; agency person cannot reach another client. |
| Location scoping | Limited member sees only their locations; organization-wide rows hidden from limited; limited member is refused for Many in Phase 3. |
| Session expiry and logout | Absolute expiry, idle expiry, revoke-all, logout, role change and membership revocation revoke sessions, Many token dies within 10 minutes (clock-controlled), grant revocation stops new assertions. |
| Duplicates | Case-variant Many emails, same email in both apps, SaaS-only and Many-only; dry-run report content; apply idempotent; no auto-merge. |
| Replay and assertion | Single-use, expiry, nbf, skew boundary, wrong `aud`/`iss`/`kid`, tampered signature, `alg` confusion (`none`, HS256 with the public key as secret), Redis outage fails closed, key rotation overlap. |
| Flag-off identical | With all flags off: new routes return 404; legacy Many JWT and SaaS cookie flows produce the same status and body for every route as the baseline; full existing suites pass; `scripts/check_instagram_frozen.py` clean; policy-copy and both contract-copy checks pass. |
| Migrations | Up to head, down one step at a time, up again, on both apps; backfill data test; downgrade leaves legacy columns. |
| Security checks | Enumeration (identical status, body, near-identical timing), lockout, reset token reuse and expiry, Host-header reset link, CSRF on mint and revoke-all, open-redirect allowlist, MFA enroll/verify/recovery, escalation attempts (§10). |
| Edge | `e2e/phase2/check_nginx.py` extended (§2.6) plus the existing 48; `nginx -t`; compose e2e six cases still pass with flags off and with SSO on. |

Nothing in this document was executed. The first real results come from the implementation session; they will be reported with exact commands.

---

## 13. Risks and open items

- The largest risk is D1/D2: until Many's global routes are workspace-scoped, client users cannot use those Many pages through SSO. This is a visible product limit, not a hidden leak.
- Email provider (D4) and first staff/Owner (D10) are operational prerequisites for cutover.
- Argon2 compatibility (§7.3) and `cryptography` availability in Many (§2.3) are unverified here.
- Many dashboard continues to hold a bearer token in `localStorage` until Phase 4.
- No tests, containers or databases were run for this document (no dependencies or Docker in this container); baselines are quoted from `docs/MERGE-PROGRESS.md`.
