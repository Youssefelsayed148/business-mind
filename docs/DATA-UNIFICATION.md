# Data unification design (Phase 5, step 5.0)

Status: **design approved 2026-11-28; 5A implemented (section 14).** Written
2026-11-28 from a read of the code. The owner accepted Q1 to Q7 of `docs/PHASE-5-PLAN.md` on
2026-11-28 ("yes for all the recommendations"); this document turns them into a buildable design.
Facts marked **(read)** come from files. Facts marked **(verify in 5A)** are not yet confirmed and
are checked first in the step that needs them.

## 1. Scope

In: a link between Many leads and SaaS contacts by channel identity; a customer view across
channels; one erasure request that reaches both systems; combined analytics; one audit view.

Out (unchanged from the plan): merging the backends (Phase 9), one database (Phase 7), new
features, cross-channel person matching by phone or name, any change to frozen Instagram
receive, dispatch or send code, live Meta or OpenAI calls.

## 2. Facts that shape the design

1. **Two identities, one key.** Many stores the external id of a person in `leads.ig_user_id`
   for all three platforms (Instagram user id, Messenger PSID, WhatsApp wa_id), scoped by
   `workspace_id` plus one account column (`instagram_account_id`, `facebook_page_id` or
   `whatsapp_account_id`) (read). The SaaS stores `contact_identities(tenant_id, contact_id,
   channel, external_id, connection_id)` (read). For delegated channels both hold the same
   external id.
2. **The two ends are joined by the connection.** `channel_connections.many_channel_ref` names
   the Many channel; the organization to workspace mapping (`tenants.many_workspace_id`,
   `workspaces.saas_tenant_id`) names the workspace (read, Phase 3/4A).
3. **Which Many data a client may read.** Client logins may call the WhatsApp and Facebook
   routes and `/privacy/contact-erasure` (Many's client scope, read). Leads, conversations,
   messages, logs and stats are global routes, **staff only** (read, Phase 4 allowlist).
   So for Instagram and Facebook people, the link and the customer view are staff-first; for
   WhatsApp, `whatsapp/contacts` (Owner or Admin) is client-readable.
4. **Erasure runs Many to SaaS today.** `POST /privacy/contact-erasure/{platform}/{channel_id}`
   erases the Many side in one transaction, then forwards a content-free `contact.erasure`
   event to the SaaS (outbox, idempotent by request id, status and retry routes) (read). The
   SaaS also has `DELETE /tenants/{id}/contacts/{contact_id}` (Admin) and an event-driven
   erase with an erasure fence of identity digests (read). Nothing starts in the SaaS and
   reaches Many. The Many half is marked "UNVERIFIED live" in its own runbook.
5. **The proxy never forwards `/privacy`** (listed in `NEVER_PREFIXES`, read). Reaching Many's
   erasure from the SaaS needs a deliberate, narrow allowlist entry (see 6.2), not a general
   opening.
6. **Cost data exists only in the SaaS** (`usage_events`). Many has none (read).
7. **Audit:** two stores with different shapes (`audit_log`, `audit_events`) (read).

## 3. Data model (SaaS side only)

One new table, reversible (drop table), no change to Many or to any existing SaaS table.

`customer_links`

| Column | Meaning |
|---|---|
| `id` | uuid |
| `tenant_id` | the organization (isolation key; every query filters on it) |
| `contact_id` | SaaS contact, nullable (a Many lead may have no SaaS contact yet) |
| `platform` | `instagram`, `facebook`, `whatsapp` |
| `many_channel_id` | the Many account or page uuid |
| `external_id_digest` | HMAC-SHA256 of (tenant, platform, channel, external id), **not** the raw id |
| `many_lead_id` | Many lead uuid, nullable (a SaaS-only identity has none) |
| `source` | `delegated_event` (SaaS contact already existed) or `many_lead` (found from Many) |
| `state` | `linked`, `many_only`, `saas_only`, `conflict`, `erased` |
| `created_at`, `updated_at` | |

Constraints: `UNIQUE (tenant_id, platform, many_channel_id, external_id_digest)` (this is what
makes duplicates impossible and the job idempotent); `CHECK` on `platform` and `state`; foreign
key `(tenant_id, contact_id)` to contacts with `ON DELETE SET NULL`; index on
`(tenant_id, contact_id)`.

Why a digest: the raw external id stays in `contact_identities` (SaaS) and in Many; the link
table adds no new copy of a person's identifier, which also keeps erasure simple (5C deletes the
row; nothing else holds the id). **(verify in 5A)** the existing erasure fence uses the same
digest function (`channels/erasure.py identity_digest`); reuse it if the inputs match.

## 4. The link job (5A)

- Runs per organization with a mapped workspace. A staff trigger (and later a periodic job)
  reads the workspace's Many leads and WhatsApp contacts through the internal Many call and
  the SaaS `contact_identities`, then upserts `customer_links`.
- Rules, in order:
  1. Same (tenant, platform, channel, external id): one row. A second sighting updates it.
  2. SaaS identity and Many lead both exist: `linked`.
  3. Only a Many lead: `many_only` (no SaaS contact is created automatically).
  4. Only a SaaS identity on a delegated channel: `saas_only`.
  5. The same external id mapping to two different SaaS contacts: `conflict`, listed for
     staff, never auto-resolved (the existing SaaS contact merge route is the resolver).
  6. No matching by phone, email or name, and no matching across channels or tenants.
- A lead whose workspace is not the mapped one is ignored (tenant isolation test in 5A).
- Idempotent: running twice changes nothing; a dry-run mode prints counts only.
- **(verify in 5A)** the exact fields of Many's `GET /leads` response (whether `workspace_id`
  is present, paging). If the response does not name the workspace, the job must use the
  workspace-scoped WhatsApp route and, for Instagram and Facebook, a staff-only workspace
  filter. If neither exists the design stops and asks (a Many route change touches areas near
  frozen code).

## 5. Customer view (5B)

- On a SaaS contact page: a section "Other channels" listing linked identities (platform,
  channel name, state) and, for staff and for WhatsApp Owner or Admin, the Many conversation
  summary for linked non-delegated channels. Read only.
- Client roles see what their role already sees; Instagram and Facebook detail from Many is
  staff-only (fact 3). The view says so instead of hiding the gap.
- No write goes into Many.

## 6. One erasure flow (5C)

### 6.1 Who and what

Owner or Admin (verified requester, as the runbook requires) starts one request for one person
in one organization. The person is chosen from a `customer_links` row or a SaaS contact, never
from a free-text phone search.

### 6.2 Steps (state machine, one case record)

`requested` → `saas_erased` → `many_requested` → `many_accepted` → `complete`
(or `needs_action` with the reason; `retry` is allowed from any non-complete state).

1. **Case:** insert an `erasure_cases` row (`tenant_id`, `request_id` uuid supplied once,
   `link_id`, state, timestamps, actor). It holds no name, message or identifier.
2. **SaaS side first**, in one transaction: the existing SaaS erase (identities, conversations,
   messages as chosen, usage references), the erasure fence digest, the audit event, and the
   `customer_links` row set to `erased` (digest kept so a later sync cannot re-create the
   link; it contains no raw id).
3. **Many side:** call Many's existing `POST /privacy/contact-erasure/{platform}/{channel_id}`
   with the same `request_id`. This needs a **narrow proxy allowlist entry** in
   `many_routes.py` for exactly the three routes (post, status, retry), Admin permission, org
   scope, not staff-only. The `/privacy` prefix stays in `NEVER_PREFIXES` for the general
   path; the entry is an explicit exception with its own test. Many already checks workspace
   Admin on its side.
4. Many erases locally and forwards a `contact.erasure` event back to the SaaS. The SaaS
   erase is **idempotent** (already erased), so the echo is a no-op, tested.
5. Poll Many's status route until `remote_status` is `accepted_not_completed` or `queued` is
   drained; record it. Many's own caveat stands: remote completion is not independently
   proven, so the case shows exactly what Many reports and never says "complete" on a guess.
   `complete` means both sides report erased; `operator_action_required` from Many becomes
   `needs_action`.
6. **Failure handling:** if Many is down or refuses, the case stays `saas_erased` with a visible
   reason and a retry button; the SaaS half is never rolled back (erasure must not be undone by a
   failure elsewhere). Re-running with the same `request_id` is safe on both sides.

### 6.3 What this does not claim

- It does not recall messages already delivered to Meta, and it does not quiesce workers; the
  runbook's maintenance-window steps still apply to active channels.
- It is tested with fakes and a throwaway Many on test data. A live run is a separate, owner-approved step.

## 7. Combined analytics (5D)

- Read model in the SaaS per organization and date range: messages (SaaS and Many), leads
  (Many) and contacts (SaaS), bot answers (SaaS), AI usage (SaaS `usage_events`). Label every
  number with its source system. **Costs = SaaS AI usage only; Many has none (fact 6).**
- Many numbers come from staff-only global stats (fact 3): shown to staff, and to clients only
  where a workspace-scoped client route exists. **(verify in 5D)** which workspace-scoped counts
  exist; if none, the client page shows SaaS numbers and says Many numbers are staff-only.
- Test: with a fixed dataset the page's numbers equal the source queries exactly.

## 8. One audit view (5E)

- A staff and Owner/Admin read view that merges, by time, the SaaS `audit_events` for the
  tenant and Many `audit_log` rows for the mapped workspace, each tagged with its source. Many's
  `/logs` is global and staff-only (fact 3), so the client part shows SaaS events and the Many
  part is staff-only until a workspace-scoped Many audit route exists (a later, separate ask).
- No copying of rows; no new write path. Both systems keep their own store.

## 9. Security and isolation

- Every table carries `tenant_id`; every query filters on it; tests with two organizations for
  the link, the erasure case and every read.
- No raw identifiers in new tables, logs or audit metadata (digests only).
- Roles: link job and conflict list: staff. Customer view: per section 5. Erasure: Owner or
  Admin; location-limited admins refused (they cannot touch whole-organization data, as in
  Phase 3).
- The proxy exception for `/privacy/contact-erasure` is the only change to the allowlist
  (section 6.2) and `scripts/test_many_proxy_allowlist.py` is extended to prove it equals Many's
  own guard.
- Feature flag `DATA_UNIFICATION_ENABLED` (default off): every new route answers 404 when off,
  like the identity and proxy flags.

## 10. Tests required (each written to fail first)

1. Link: no duplicates on a synthetic dataset with repeated identities; re-run is a no-op;
   conflict case listed, not merged; other-tenant and other-workspace rows ignored.
2. Link on a **restored copy** of data (owner supplies the copy): zero duplicates, counts
   match, run time recorded.
3. Erasure: both sides end with no data for the person on test data; same `request_id` twice
   changes nothing; Many down leaves `saas_erased` with a retry that completes; the echo event
   is a no-op; a later link sync does not re-create the link.
4. Isolation: tenant A cannot see, link or erase tenant B's people (every route).
5. Analytics: numbers equal sources. Audit view: ordering and source tags.
6. Flag off: every new route 404 and every existing behaviour unchanged.
7. `scripts/check_instagram_frozen.py` in every gate.

## 11. Steps and rollback

5A link, 5B customer view, 5C erasure, 5D analytics, 5E audit view, 5F close (WSL gates, restored
copy). One branch and one draft PR each; each stops for review. Migrations are chained on the
real heads (check `alembic heads`; SaaS `0035_invitation_locations` read 2026-11-26), have
downgrades, and are tested upgrade and downgrade. Rollback: flag off; downgrade drops the new
tables; nothing in Many changes.

## 12. Open questions for the owner

1. **Staff-first for Instagram and Facebook people** (fact 3): accept that clients see only
   WhatsApp contacts and SaaS data in the customer view, with Many detail for the other two
   channels staff-only? (Recommended: yes; widening needs Many route changes near frozen code.)
2. **Case record retention:** keep erasure cases (no personal data) for how long?
   (Recommended: the same period as audit events.)
3. **Link job trigger:** staff button first, periodic job later? (Recommended: yes.)
4. **A Many-side audit route per workspace** (so clients can see Many audit entries): later and
   separate, since it adds a Many route. (Recommended: not in Phase 5.)
5. **The restored copy** for test 2: the owner supplies it (never a live database).

## 13. Owner decisions (2026-11-28)

- Q1 to Q7 of the plan: accepted as recommended.
- Section 12 question 1 **changed by the owner**: a client Owner or Admin may see WhatsApp,
  Instagram **and** Facebook people in the customer view (not staff-only). The browser still never
  reaches Many's global routes: the SaaS reads Many on the server (5A, staff-triggered) and the
  client reads the SaaS link table. Rows are tied to the organization by the channels it owns
  (section 14), so one organization never sees another's people. This widens 5B; it is built there
  with role and isolation tests.
- Section 12 questions 2 to 5: recommendations accepted (case retention like audit events; staff
  button first; no Many-side audit route in Phase 5; the owner supplies the restored copy).

## 14. 5A record (2026-11-28)

Built: flag `DATA_UNIFICATION_ENABLED` (default off), migration `0036_customer_links` (tables
`customer_links` and `many_channel_claims`, reversible), `app/linking/{service,fetch,router}.py`,
staff routes under `/api/v1/platform/tenants/{id}/` (`customer-links/sync` with `dry_run`,
`customer-links`, `many-channel-claims`). All answer 404 while the flag is off.

Verified from Many's code (this closes the "(verify in 5A)" items):
- `GET /leads` returns **every workspace's** leads with no workspace id; each lead names its
  channel (`instagram_account_id`, `whatsapp_account_id` or `facebook_page_id`), `platform`, and
  the external id in `ig_user_id`.
- `GET /instagram/accounts` is global and does **not** name a workspace; `routes_instagram.py` is
  frozen for client scope, so it is not changed. WhatsApp and Facebook account lists are
  workspace-scoped.
- Therefore ownership of channels is: WhatsApp and Facebook from the workspace-scoped lists;
  Instagram from the organization's own channel connections **plus explicit staff claims**
  (`many_channel_claims`, one channel to one organization, audited). Leads on channels the
  organization does not own are ignored. No Many or Instagram change was needed.

Deviations from section 3: the digest is a domain-separated SHA-256 (same family as the existing
erasure fence), not an HMAC, because no secret exists in every environment. It is pseudonymous,
not anonymous (a guessable phone number could be tested against it); the table is tenant data and
cascades with the tenant. A keyed digest is a later hardening. The contact foreign key is a plain
`SET NULL`; the tenant match is enforced in code and by tests.

Not in 5A: the periodic job (staff button only), the client-facing view (5B), erasure (5C).

## 15. 5B record (2026-11-28)

Built (client view of the link, Owner and Admin only):
- API: `GET /api/v1/tenants/{id}/customer-links` (filters `platform`, `state`, `q`; paging) and
  `GET /api/v1/tenants/{id}/contacts/{contact_id}/customer-links`. Both need the new permission
  `org.customer_links` (Owner and Admin; the `org.` prefix keeps agency people out, so an agency
  Admin does not see a client's people), refuse location-limited access, hide erased rows, answer
  404 while the flag is off, and never return a raw external id.
- `customer_links` gained `display_name` (the username Many holds) and `lead_seen_at`, so a client
  can see who a Many-only person is. This is personal data; erasure (5C) removes the whole row.
  The unreleased migration `0036` was amended instead of adding `0037`.
- `GET /auth/config` names `data_unification: true` only while the flag is on.
- Web: `/app/{tenant}/contacts/links` ("People across channels": filters, search, paging, Arabic
  names isolate their direction), a button on the Contacts page and a "Channels across systems"
  card on the contact page, both shown only when the API answers.
- Existing tests changed: `tests/test_role_matrix.py` (new permission row `org.customer_links`).
  The two new routes are in `TENANT_ROUTE_PERMISSIONS` and `TENANT_ROUTE_ROLES`.

Not in 5B: Many conversation summaries inside the customer view (Many's conversations and
messages are global staff-only routes; showing them to clients needs a workspace-scoped read that
does not exist, so it stays a later, separate ask), a menu entry, role-specific browser tests
(roles are covered by the API matrix).

## 16. 5C record (2026-11-28)

Built: one erasure request for one person on one channel, started by an Owner or Admin from the
people page (confirmation dialog, one request id per click).
- Migration `0037_erasure_cases`: table `erasure_cases` (state, reason code, opaque ids; no name,
  message or identifier) and column `customer_links.external_id`. Reversible.
- `app/linking/erasure.py`: records the case first, erases the SaaS side with the existing audited
  routine (`channels.erasure.erase_channel_contact`, fed a `contact.erasure` event row), scrubs the
  link (state `erased`, name, lead id, contact id cleared), then asks Many with the **same request
  id** through Many's existing `POST /privacy/contact-erasure/{platform}/{channel_id}` (called
  directly by the server as the acting user, so no allowlist change was needed; section 6.2's
  "narrow proxy exception" is not used). The raw id is scrubbed when Many reports `local_status:
  erased`. A Many failure never undoes the SaaS erase: the case becomes `needs_action` with a
  plain reason and **Try again** repeats the Many call with the same request id.
- Routes (permission `org.customer_erase`, Owner and Admin, not agency, not location-limited, 404
  while the flag is off): `POST customer-links/{id}/erase`, `GET erasure-cases`,
  `POST erasure-cases/{id}/retry`.
- Web: an Erase button per row and an "Erasure requests" card with retry.

Changes to the design:
1. **The raw external id is now stored** on the link row (`external_id`) until the erasure
   completes. Reason: Many can only be asked to erase a person by external id, a client cannot read
   it from Many, and the SaaS has it only if it keeps it. It never goes to the browser and is
   removed at completion. (The digest stays for uniqueness.) The owner should confirm this.
2. **"Complete" means Many reports its local erase.** Many's `remote_status` describes Many's own
   forward back to the SaaS, which is a no-op here (already erased); it is stored for information.
3. Erasing one channel identity deletes the SaaS **contact** (the existing routine does this), so
   the same person's links on other channels stay until each is erased too. The dialog says so.
4. Many's side is still "UNVERIFIED live" (its own runbook); everything here ran against a fake.

## 17. 5D and 5E record (2026-11-28)

5D, combined overview (`GET /api/v1/tenants/{id}/customer-overview?days=7..365`, permission
`org.customer_links`, Owner and Admin, flag-gated; shown as a card at the top of the people page):
- People by channel and state, people known to the outreach service, people known to the chat inbox
  (from the customer link); chat contacts, conversations, handoffs and messages by sender
  (visitor, bot, agent) in the period; bot calls, tokens and the measured cost (SaaS).
- Playground threads and playground usage never count; other organizations never count.
- Every block carries its source. **Costs:** only the SaaS records them (`cost_usd` on some calls),
  shown as "Not measured" when no call has one. Many records none and offers no per-organization
  message counts, so the response lists those as "not available" instead of guessing.
- Test: a fixed dataset where each number equals the source tables (and a direct SQL cross-check),
  a longer period includes older rows, two identical organizations are not summed, empty zeros.

5E, combined audit trail (`GET /api/v1/platform/combined-audit?source=all|saas|many&tenant_id=&limit=` (not `/platform/audit`, which already exists for the Operations page),
platform staff only, flag-gated; page `/platform/audit`, linked from the staff Logs page):
- SaaS audit events and Many's `/logs`, newest first, each row tagged with its source; only the
  action, a short sentence and a level are returned (no metadata, no target, no actor).
- **Not per organization for Many:** Many's log is global and names no organization, so with a
  tenant filter only SaaS events are shown, with a note. If Many does not answer the SaaS rows still
  show, flagged. A workspace-scoped Many audit route stays a later, separate ask (question 4).
- For clients (Owner and Admin) the SaaS trail they already have (`data/audit`) now also contains
  the link sync, claim and erasure events, and no personal data.
- Both systems keep writing their own store; nothing is copied.

Existing tests changed in 5B to 5E: `tests/test_role_matrix.py` (permission rows
`org.customer_links` and `org.customer_erase`), `tests/test_identity_migrations.py` (head and chain),
`group-b-client-visibility.spec.ts` and `group-c-fixtures.ts` (the fake API answers 404 for the new
routes, like the real API does with the flag off).

## 18. Restored-copy check (the owner runs it; step 5F)

Needs restored copies of both live databases on a throwaway stack (never a live database), the
migrations applied (`alembic upgrade head`: SaaS head `0038_grant_location_scope`; the link tables come from `0036` and `0037_erasure_cases`), the organization to
workspace mapping set for one pilot organization (`scripts/identity_migrate.py map-apply`), and
`DATA_UNIFICATION_ENABLED=true` with the proxy prerequisites. Then, as platform staff:

1. Dry run: `POST /api/v1/platform/tenants/{id}/customer-links/sync?dry_run=true`. Read `created`,
   `ignored_leads` and `by_state`. Nothing is written.
2. Real run: the same call without `dry_run`. Then run it again: `created` and `updated` must be 0.
3. Duplicates (must return no rows; the unique constraint makes it impossible, this proves it):
   `SELECT tenant_id, platform, many_channel_id, external_id_digest, count(*) FROM customer_links
   GROUP BY 1,2,3,4 HAVING count(*) > 1;`
4. Counts: `SELECT platform, state, count(*) FROM customer_links GROUP BY 1,2;` against the number
   of Many leads on that organization's channels (leads with `whatsapp_account_id`,
   `facebook_page_id` or an `instagram_account_id` the organization owns).
5. List `conflict` rows through `GET .../customer-links?state=conflict`; each needs a staff merge.
6. Note the elapsed time of step 1 for the cutover rehearsal (Phase 7).

A synthetic stand-in runs in `tests/test_customer_links.py` (2,000 people repeated three times, 300
already chat contacts): 2,000 rows, none duplicated, the second run changes nothing, about a second
per run. It is not a substitute for the real copy.

## 19. 5F record (2026-11-28, cloud container: Node 24.22.3, Postgres 16, no Docker)

Gates observed:
| Gate | Result |
|---|---|
| SaaS API suite (pgvector 0.6.0) | 1608 passed, 10 failed: the same 10 named pgvector tests as the 4F run (embedding readiness 3, hybrid retrieval 4, r19 index 1, RAG evaluation 2) |
| Phase 5 API tests (links 16, client view 7, erasure 15, overview 5, audit 6) plus migrations, role matrix, route matrix | all pass |
| Web (Node 24): lint, typecheck, logical-CSS | clean; unit tests 6 files |
| Full web Playwright suite (Node 24) | 306 passed, 0 failed, 3 skipped |
| ruff, format, strict mypy; `check_instagram_frozen.py` | clean; OK. No Many file changed in Phase 5 |

Real faults the regression suites caught, all fixed with a test:
1. The combined audit route first used `GET /api/v1/platform/audit`, which already exists for the
   Operations page; with the flag off it answered 404 and broke that page. Renamed to
   `/combined-audit`; a test now checks the old route stays untouched with the flag on and off.
2. The new people routes ran the role check before the flag check, so a low role got 403 instead of
   the "unknown route" 404 with the flag off. The flag now runs first, like the identity routes.
3. The new routes were missing from the exact route-contract test and the platform route list.

Existing tests changed in Phase 5: `test_role_matrix.py` (two permission rows, flag helper for its
three HTTP matrices), `test_tenant_route_matrix.py` (route count 102 to 108, flagged routes, two
path ids), `test_identity_migrations.py` (head and chain), `group-b-client-visibility.spec.ts` and
`group-c-fixtures.ts` (fake API answers 404 for the new routes).

Not run here and needed on the owner's side: the restored-copy duplicate check (section 18, needs
a copy from the owner), `scripts/dev-up.sh test` and nginx checks (no Docker), the Many suite (no
Many file changed, but the owner's gate), both backend suites on Postgres 15 and 17 (WSL), real Many
behind the sync and the erasure call (only a fake answered), a real Meta-side erasure, mobile and
right-to-left screenshots of the new pages.

## 20. Change log

- 2026-11-28, Claude Code: design written from a read of both data models, the Many erasure
  routes and runbook, the proxy allowlist and the SaaS erase code. Docs only; nothing run.
