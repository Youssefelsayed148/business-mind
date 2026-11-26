# Merge progress

## Done
- Phase 0: plan agreed; Instagram policy = option 2; repo business-mind created and attached.
- Phase 1 (partial), branch `phase-1/foundation`:
  - [x] Repo checked: only the 4 bootstrap docs were present.
  - [x] Pre-import secret scan of both source histories (filenames + regex + shape triage); two credential paths found in Many.
  - [x] Many history rewritten without `popeye access token.txt` and `dashboard/.env.local` (filter-branch, 114/114 commits, 0 dropped); proofs in `docs/IMPORT-NOTES.md`; old->new map in `docs/legacy/many-commit-map.txt`.
  - [x] Many imported as root (114 commits), SaaS imported under `modules/saas/` (457 commits, tree identical to source, layout kept as-is).
  - [x] Old CLAUDE.md/AGENTS.md moved to `docs/legacy/` with a README; `docs/IMPORT-NOTES.md` written.
  - [x] `docker-compose.merge-dev.yml` + `.env.merge-dev.example` added (validated with `docker compose config` only; never started).
  - [x] gitleaks 8.30.1 scan of the branch history: 34 findings, all fake test fixtures (see IMPORT-NOTES).

- **Phase 3 backend (identity): reviewed and approved for merge, 2026-11-26.** PRs #6 (A), #7 (B), #8 (C), #9 (D) and the review-fix PR, merged in that order with merge commits (this record reaches `main` with the last one). Findings, fixes, gates and open items: `docs/PHASE-3-REVIEW.md`. All identity flags stay OFF. Not met: "one login reaches every page" (no web screens, no Many SSO, no organization to workspace mapping writer).

## In progress
- **Phase 4: step 1 done; 4A to 4E implemented and waiting for the owner's review** (4E record: plan section 16; 4F not started) (4C/4D record: `docs/PHASE-4-PLAN.md` section 15; 4E and 4F not started) (branch `claude/blissful-allen-b63jty`, draft PR #12 into `docs/phase-4-plan`). 4B (shell): real-role display, menu data, switcher rule, shared page states, Many client, the `/platform/many` page, old-URL redirects, logical-CSS check; record and gates in `docs/PHASE-4-PLAN.md` section 14. 4C is not started.
- (4A detail) **Step 1 done (owner accepted P1 to P8 as recommended, 2026-11-26); step 4A implemented** (branch `claude/blissful-allen-b63jty`, draft PR #12 into `docs/phase-4-plan`). 4A: org to workspace mapping command, MFA code race fix, Phase 3 review items 3 and 7, staff workspace access and additive SSO memberships in Many, the server-side Many proxy (off by default). Full record, deviations and gates: `docs/PHASE-4-PLAN.md` section 13. 4B is not started.
- (History; implemented and reviewed since, see Done) **Phase 3 (One identity) = DESIGN DONE AND APPROVED 2026-11-24 (owner approved D1 to D10 with the recommended defaults); implementation not started. Branch `phase-3/identity-design` (docs-only draft PR), 2026-11-24.** Done in this session: read-only discovery of both apps' users, hashes, sessions/JWT, roles, tenants, invitations, reset, MFA, audit, logout, rate limits and every route (`docs/IDENTITY-DISCOVERY.md`, file:line cited) and the design (`docs/IDENTITY-DESIGN.md`: summary and decisions, contradictions with the decided model, SSO assertion flow, data-model options for agencies and locations with recommendations, role matrix, team management, migration, flags, threat model, implementation and test plans). **No application code, no tests run, no migrations written.** Implementation (tasks 3 to 7) waits for owner approval of the design and runs later on the owner's machine. Biggest finding: Many's global routes (Instagram, campaigns, conversations, messages) do not filter by workspace, so Instagram cannot join the organization model through mapping data alone (design decisions D1/D2).
- **Phase 2 = DONE: PR #3 merged into main (`940e74a`).** Independent review found no blockers and three low items, all handled in Phase 2b: (1) mixed DNS answers for a listed host now fail closed (commit `ddb4051`); (2) RUNBOOK-DEV documents that `CHANNEL_INTERNAL_ALLOWED_HOSTS` is whitespace- and trailing-comma-sensitive and that invalid values fail startup; (3) `docs/PHASE-2-RESULTS.md` states that the e2e runs in development over http, so the production-HTTPS rule is covered by unit tests only. Security notes remain binding: not full SSRF parity, trusted compose-DNS boundary, Many double DNS resolution (transport pinning = Phase 6, owner approval needed), allowlist is deployment config only. Phase 6 candidates: Many transport pinning; optional `host:port` allowlist entries; PR trigger for the SaaS CI.
- (History; merged as PR #4 on 2026-11-24) **Phase 2b = IN PROGRESS, branch `phase-2b/unified-compose` (draft PR to be opened after the owner allows the push), 2026-11-24.** Implemented locally: unified compose (`docker-compose.unified.yml`, no-egress `docker-compose.unified.e2e.yml`, prod overlay `docker-compose.unified.prod.yml` written and never deployed), `nginx/unified.conf` (deny of Many's signed `/api/saas/*` and `/saas/*` and of SaaS `/api/channels/*` on both SaaS hosts; `nginx/default.conf` untouched), `.env.unified.example` (placeholders only), `scripts/dev-up.sh` (up|test|down), `backend/constraints.txt` (MD5 `4c30f8ed…` matches the freeze; no index URLs or credentials), `docs/RUNBOOK-DEV.md`, `docs/DEPLOY-OUTLINE.md`, edge checks `e2e/phase2/check_nginx.py`. Results: `docs/PHASE-2-RESULTS.md` section 4. SaaS CI workflow added as `.github/workflows/saas-ci.yml` (manual `workflow_dispatch` only, no secrets, `contents: read`; **never executed, Actions paused**; header lists the r19 deselect and the `format:check` continue-on-error). No push yet. **Owner decisions 2026-11-24:** keep the production HTTPS requirement (no relaxing); internal TLS with a private CA and edge TLS are **Phase 6 items, open**; the prod overlay stays written-not-deployable.
- **GitHub Actions is paused for billing: every gate stays local** (full suites in WSL, `scripts/check_policy_copies.py`, both contract checks, `scripts/dev-up.sh test`). The workflow `phase2-policy-copies.yml` ran once on PR #3 (pass) before the pause.
- **Phase 2 preflight (2026-11-23, Codex), branch `phase-2/one-infrastructure`**: created from main at `8450ae5` after verifying merge commits `047ba53` and `8450ae5` (two parents each), Phase 1b ancestry, Many/SaaS history counts 114/457, and empty `git log --all -- "popeye access token.txt" dashboard/.env.local`. Implementation stopped at the internal-network security-policy conflict below; no application or workflow changes.
- **Phase 1b (verification) done on branch `phase-1b/verification`**: for every suite present in both trees the merged repo equals the original; see `docs/PHASE-1B-RESULTS.md` (draft PR against `phase-1/foundation`).
- Phase 1 exit criteria: history yes; suites match originals yes (with the caveats in PHASE-1B-RESULTS); draft PR #1 yes; no secrets yes. PR #1 and the Phase 1b PR (#2) were merged on 2026-11-23.

### Phase 1b result summary (WSL Ubuntu, Docker pg15 / pg17+pgvector / redis7; same for original and new)
| Suite | Original | New |
|---|---|---|
| Many backend pytest | 1007 passed / 0 / 0 skipped | 1007 passed / 0 / 0 skipped (= recorded baseline) |
| Many scripts unittest | 29 OK | 29 OK |
| Many dashboard tsc / lint | exit 0 / exit 0 (1 known warning) | same |
| SaaS API pytest | 1215 passed, 1 failed (env: PGHOST socket) | identical; the 1 test passes in both when its env is supplied |
| SaaS ruff / mypy | pass / pass | pass / pass |
| SaaS web unit / lint / typecheck | 8 pass / exit 0 / exit 0 | same |
| SaaS web format:check | exit 2 (4 files) | exit 2, same 4 files (pre-existing) |
| Contract copies (Many root, SaaS root) | OK / OK | OK / OK (no path broken by the move) |

NOT RUN: SaaS Playwright e2e, npm audit, next build, full SaaS pytest re-run with PGHOST (reasons in PHASE-1B-RESULTS).

### Phase 2 allowlist results (2026-11-24, WSL + `unshare -rn` no-egress netns, Docker Postgres via socket bridges; observed values only)
| Check | Result |
|---|---|
| Many full suite, allowlist empty | 1007 passed / 0 failed / 0 skipped (matches baseline) |
| SaaS full suite, allowlist empty, DB name `saas_p2_full_test`, socket env set (re-run 2026-11-24) | 1277 passed / 0 failed / 0 skipped (includes the 61 new tests; excluding them: 1216 passed / 0 failed). The earlier 1215/1 was my runner's DB name, not app code |
| New policy tests | Many 61 passed; SaaS 61 passed |
| SaaS ruff check / ruff format --check / mypy (4 touched files) | clean / clean / no issues |
| Many lint | the repo has no ruff configuration; none run |
| `scripts/check_policy_copies.py` | OK, byte-identical |
| `scripts/check_contract_copies.py` | OK (3 LF-normalised hashes) |
| Alembic heads (read from the scripts, no DB) | Many `0030_meta_account_erasure`; SaaS `0031_contact_erasure` (no migration added) |
| Six compose e2e cases (3 channels x delegation ON/OFF), re-run 2026-11-24 | `SUMMARY case1..case6 = PASS`; health: many-api `/health` 200, saas-api `/ready` 200, pg15/pg17/redis healthy; Many worker -> `saas-api` (6 event POSTs), SaaS worker -> `many-api` (3 `/api/saas/messages`), 3 Meta sends to mock-meta. Full output and per-call destinations saved in `docs/PHASE-2-RESULTS.md` |
| Security review | no confirmed finding at confidence >= 8; limitations (a), (b) above |

### Phase 2b end-of-2b gate (2026-11-24, local, allowlist empty, `_test` DB names, no-egress netns)
| Check | Result |
|---|---|
| Many full suite | 1084 passed / 0 failed / 0 skipped (1007 baseline + 77 policy tests). A first attempt skipped 638 tests because the socket bridge was stale (harness fault) and was repeated |
| SaaS full suite | 1293 passed / 0 failed / 0 skipped in 1910 s (1216 baseline + 77 policy tests; DB `saas_p2_gate2b_test`) |
| Policy tests | 77 passed on each side; SaaS ruff / format / mypy clean; `check_policy_copies.py` OK |
| Contract checks (Many root, SaaS root) | OK / OK |
| Alembic | no migration file changed since main (Many `0030_meta_account_erasure`, SaaS `0031_contact_erasure`) |
| Unified stack through nginx (`scripts/dev-up.sh test`) | six e2e cases PASS; 41/41 nginx edge checks PASS (signed routes 403 in every spelling on every host; admin routes get the app's 401); `nginx -t` OK; details in `docs/PHASE-2-RESULTS.md` section 4 |
| Instagram / frozen code | not touched: changed paths vs main are the policy module copies and their tests, e2e driver (`run_cases.py`, `check_nginx.py`), compose/nginx/docs files |

Local state kept for the owner (no cleanup until Phase 2b is done): `unified-e2e` stack (running), `p2e2e` stack, `merge-dev-*` DB containers, images `p2e2e-*` and `unified-*`, WSL `~/phase2/` scratch and socket bridges.

## Phase 3 PR A: identity, Many side (branch `phase-3/identity-impl-a`, 2026-11-24, WSL + Docker, observed values only)

| Check | Result |
|---|---|
| Baselines, flags off, throwaway DBs, no egress | Many 1084 passed; SaaS 1293 passed (1807 s) |
| EdDSA in Many | `cryptography==50.0.2` and `pyjwt==2.15.1` pinned in `backend/constraints.txt`; sign/verify with `kid` worked inside the Many image |
| Argon2 compatibility (synthetic hashes) | passlib 1.9.5 and argon2-cffi 25.1.0 verify each other's argon2id hashes (both m=65536,t=3,p=4); older parameters verify and are flagged for rehash; non-argon2 strings are rejected. Many hashes can be carried over |
| Many full suite at commit 2 / commit 5 | 1096 passed / 1156 passed |
| Many full suite at commit 7 | 1278 passed, 1 failed (`test_tampered_and_garbage_are_refused`: the test overwrote the signature's last two characters, a no-op about 1 time in 256). Fixed in a test-only commit; that file re-run alone: 18 passed. The full suite was not re-run after the fix |
| Migration `0031_sso_link` | up, down, up on a private DB with legacy rows intact; `alembic check` shows no drift |
| Flag-off identical | legacy credentials give the same status on every route (5 credential variants x all routes) with the flag off and on; login claims identical |
| Client-scope guard | live request per route: every non-allowlisted route denies a client token (all Instagram routes included); allowlist holds only workspace-scoped routes; mutation check (adding `/instagram`) fails the tests as intended |
| `check_instagram_frozen.py`, policy copies, both contract checks | OK, OK, OK, OK; 6 unit tests for the frozen check |
| `scripts/dev-up.sh test` | six e2e cases PASS; 48/48 nginx checks PASS (a first attempt failed at image build on a pip network error, retried once). It tore down the old `unified-e2e` stack from Phase 2b |
| Secret scan | regex scan of added lines and file names: clean (no scanner installed) |
| SaaS | not changed by PR A; SaaS suite not re-run after the baseline |

Deviations from the design: `channel_location_map` not created (nothing reads it yet); migration steps are guarded because `0001_initial` bootstraps from current models; a shadow user whose email collides with an existing Many user gets a placeholder email and is never linked. Known gaps: GET on `/auth/sso/exchange` answers 405 with the flag off (POST gives the unknown-route 404); no in-app rate limit on the exchange (edge zone is PR C); a user's SSO membership is exactly one workspace at a time, so two orgs in two tabs would flip it.

## Phase 3 PR B: identity, SaaS side (branch `phase-3/identity-impl-b`, stacked on `phase-3/identity-impl-a`, 2026-11-25, WSL + Docker, observed values only)

| Check | Result |
|---|---|
| Migrations 0032 / 0033 / 0034 | chain on `0031_contact_erasure`; single head; up, down, up with legacy rows intact; backfill maps viewer, editor to agent, admin and promotes nobody; downgrade clears only the mapped values (`tests/test_identity_migrations.py`, 5 tests) |
| `alembic check` drift | first full run failed `test_r19_index_migration` because the models lacked the `location_id` FK and index; fixed in the models; that file and 9 related migration/drift tests pass (10 passed) |
| SaaS full suite (flags off, throwaway DB, no egress) | 1325 tests, 0 errors, 1 failure (the drift above, since fixed). 1293 baseline + 32 new. The full suite was not re-run after the model fix; 91 tests touching contacts, channels, knowledge, inbox and the new files re-ran green |
| Role matrix | golden design table vs `roles.py`; every live tenant route (92 + `POST /tenants`) has one permission; 7 roles/actors x every route over HTTP with the flag on; legacy viewer/editor/admin responses per route with the flag off; no legacy ability lost, only knowledge routes widen (D5) |
| Flag-off identical | `org_role`, location scope and agency grants are ignored with `IDENTITY_V2_ENABLED` off (tested); streaming routes (inbox events, playground stream) are not called live for allowed roles in the matrix |
| Agency grants / locations | 13 + 6 tests: no access without grant and assignment, cap below Owner, no team/agency/billing/org, expiry per request, immediate revocation, audit with both ids, cross-tenant FKs refused by the database |
| Lint / types | `ruff check`, `ruff format --check`, strict `mypy` (305 files): clean |
| `check_instagram_frozen.py`, `check_policy_copies.py` | OK, OK; no Many or Instagram file touched |
| Secret scan | regex scan of added lines: only identifier names (token_hash, password_hash), no values |

Deviations from the design: `agency_grants.location_ids` is a join table (`agency_grant_locations`) for referential integrity; the stored `editor` role is the Agent role (alias, no data rewrite); a direct membership wins over an agency grant (can only narrow). Known gaps: location-limited callers are refused on every tenant route with the flag on until query sites use `locations.location_filter`; agency users hold no `org.read`, so they cannot open the tenant detail route; the permission map is enforced only through `get_tenant_context` (platform routes unchanged); no grant management routes yet (service functions only; routes belong with PR C team/agency UI).

## Phase 3 PR C: identity, issuing and team (branch `phase-3/identity-impl-c`, stacked on `phase-3/identity-impl-b`, 2026-11-25, WSL + Docker, observed values only)

Review of PRs #6 and #7 (owner asked for a review, then PR C; all three are to be merged together, A then B then C):
- No blockers. Five nits fixed. PR A (`685c111`): jti TTL 120 -> 150 (the widest verifiable window is exactly 120 s), shadow-user creation in a savepoint so a concurrent first exchange reuses the winner instead of a 500 (`user_conflict` / `user_inactive` refusals), client scope `/workspaces` prefix replaced by the exact `/workspaces/me`. PR B (`f6a9ee8`): grant creation uses a savepoint instead of `rollback()`, same-cap grants resolve narrowest first deterministically. PR A was merged into PR B with a merge commit (no rebase, no force-push).
- Tests at that point: Many 201 passed (sso session, assertion, guard, exchange, config, flag-off identical); SaaS agency grants, role matrix and location scope 29 passed.

Commits (all behind flags that default OFF; flag-off identical is proven per commit, see the notes):

| Commit | What | Own tests |
|---|---|---|
| (a) `f150459` | `org.summary` and `GET /tenants/{id}/summary` (agency gets it, still no other `org.*`) | 14 |
| (b) `929078b` | SSO issuing: `POST /api/v1/sso/assertions`, `GET /api/v1/sso/authorize`, EdDSA 60 s, mfa claim, exact redirect allowlist, state | 31 |
| (e) `c9f3dcc` | console mailer (built before c and d, which send through it) | 4 |
| (c) `fcbf1d3` | team management: invitations v2, new-account acceptance, role change, deactivate, last-Owner rule, grants for the Owner, agency-admin assignment | 36 |
| (d) `a7f65b5` | reset, TOTP MFA, session idle/absolute policy, device list, revoke-all, login buckets, dummy hash, audit events | 49 |
| (f) `f4743b7` | `scripts/identity_migrate.py` (dry-run default, advisory lock, hash algorithm of every Many row) | 13 (Many venv) / 12 + 1 skipped (SaaS venv) |
| (g) | `nginx/unified.conf` exchange location + limit zone + case-insensitive twin, `check_nginx.py` +21 checks, `.env.unified.example`, compose passthrough | 69 edge checks |
| (h) | `docs/RUNBOOK-DEV.md`, `docs/DEPLOY-OUTLINE.md`, this file | n/a |

End-of-PR gate (each run once, on a snapshot of the final tree unless noted):

| Check | Result |
|---|---|
| SaaS full suite (`p3repo.sh saas full_test`, DB `saas_p2_full_test`, no-egress netns) | 1441 passed, 4 warnings, 26 min 26 s |
| Many full suite (`p3repo.sh many full`, DB `many_test_r1`) | 1286 passed, 3 warnings, 2 min 58 s |
| ruff check / ruff format --check / strict mypy over `app tests alembic` (SaaS) | clean / 334 files formatted / 327 source files, no issues |
| `scripts/check_instagram_frozen.py` | OK, 5 frozen files identical to `origin/main` |
| `scripts/check_policy_copies.py` | OK, byte-identical |
| `scripts/check_contract_copies.py` and `modules/saas/scripts/check_contract_copies.py` | both OK |
| `scripts/dev-up.sh test` (unified stack, no egress) | six e2e cases PASS; nginx edge checks 69 of 69 (the 48 existing + 21 new); `nginx -t` ran with the container start. A first run was 68 of 69: my new burst check wrongly assumed a fresh limiter bucket; the check was fixed and the run repeated (images reused, `NO_BUILD=1`) |
| Secret scan over every line this branch adds vs `origin/main` | no key, token or credential patterns; only synthetic test passwords. `unified-e2e.env` was already tracked (throwaway values) |
| Cross-check, one-off | a SaaS-signed assertion passes Many's real `verify_assertion` (separate venvs); one with `locations` set is refused by it |

Notes:
- The new routes (summary, team, grants, reset, MFA, sessions, SSO issuing) are in the OpenAPI document with their flags off, but answer exactly like an unknown route (404 `{"detail":"Not Found"}`, before authentication and body validation). The exact route-count contract test now expects 102 tenant routes (was 93).
- Decision 2 holds: no request body can assign location scope `limited` (invitations, role change and grants reject location fields); `LOCATION_SCOPE_UNSUPPORTED` stays; the flag stays off. PR D lifts it.
- Revoking a grant, changing a role, deactivating a member and resetting a password or MFA revoke the affected sessions (design 6.5); two older tests now expect a 401 right after a grant is revoked.

Not built or not applied (details in the final report): any web UI (team, invite acceptance, reset, MFA pages); an API to create agencies or add agency people (staff only via the service layer); memberships and the org-to-workspace mapping in `identity_migrate.py`; an enrollment-only session state for MFA (enforcement happens when an assertion is minted); an in-app rate limit on the Many exchange (the edge zone only).

## Phase 3 PR D: location filters (branch `phase-3/identity-impl-d`, stacked on `phase-3/identity-impl-c`, 2026-11-25, WSL + Docker, observed values only)

What changed (all behind `IDENTITY_V2_ENABLED`, default OFF):
- Location filters on inbox (list, counts, detail, actions, SSE stream), bot conversations, follow-ups, contacts (list, detail, update, export, merge, erase, stage rename), knowledge sources and documents, channels list, and analytics (bot-level and organization-level raw SQL). Conversations take their connection's location; website conversations and NULL-location rows are organization-wide, so limited callers never see them. Contacts take a location at creation (API body, or the connection's location for channel contacts).
- Limited callers get 403 on jobs, revisions, contact stage rename, and merge/erase of a contact that has conversations outside their locations. Team changes need unrestricted access.
- Team API: invitations, role change and agency grants take `location_scope` / `location_ids`; migration `0035_invitation_locations`; accepted invitations (new or existing account) copy the scope; Owners are never limited; a limited Admin does not count as the last Admin; role change keeps the scope when omitted and revokes the member's sessions.
- `LOCATION_SCOPE_UNSUPPORTED` removed from the tenant context. The SSO exchange for Many still refuses limited people (design 4.2).
- Staff can set a channel connection's location (honored only with the flag on).

Gate results (each run once; details in the PR):
- SaaS full suite on commits 1-2: 1452 passed, 7 failed (4 inbox-sweep fake taking 3 args, 2 audit-metadata shape, 1 DB name needing the `_test` suffix from my run tag). All 7 fixed in commit 4 and re-run: 62 passed in the affected files plus the new location files. The full suite was NOT re-run end to end after commits 3 and 4.
- Channel tests after commit 3: 59 passed. New tests: 21 (14 in `test_location_filters.py`, 7 in `test_location_assignment.py`); two old tests that expected the refusal were replaced and the migration test now expects head 0035.
- ruff, ruff format, strict mypy over `app tests alembic`: clean. Frozen-Instagram, policy-copy and contract-copy checks: OK. Secret scan of added lines: clean.

Not done / open:
- No API to change a source's or an existing contact's location after creation (staff upload leaves sources organization-wide, so limited people see no sources until one exists).
- Duplicate-contact checks (409) still look across the whole organization.
- Many-side `channel_location_map` and limited access to Many routes stay deferred.
- The SSE stream fixes the caller's scope when it connects.

## Next
- **The Phase 4 plan, status, decisions and known gaps are in `docs/PHASE-4-PLAN.md`; update it every Phase 4 session. Next after the review of 4A to 4E is 4F (close: deny the public exchange at the edge, nginx paths, screenshots, old-tab walk, full gates on the WSL stack); show the plan first. 4C and 4D were built together with four page-porting agents (plan section 15).**
- **Phase 4 (one dashboard), step 1: WRITTEN, awaiting the owner's review (was greenlit 2026-11-26).** Write `docs/UI-INVENTORY.md` (every page of both apps: route, purpose, API, role) and the menu, naming, language/RTL and theme proposal, then stop for approval. Owner decision 2026-11-26: Many pages that client logins cannot open (campaigns, conversations, messages, leads, logs, stats, Instagram) start as staff-only in the unified UI.
- Phase 4 must also cover the identity wiring Phase 3 left out: server-side SSO exchange in the new shell (the public exchange is removed then, D3), the organization to workspace mapping, and the team, invitation, reset and MFA screens.
- Before enabling any identity flag: decide the items in `docs/PHASE-3-REVIEW.md`, "Open before enabling any flag".
- (History) Phase 3 (owner decisions on PR B, 2026-11-25, recommendations accepted): (1) agency users get a narrow read-only `GET /api/v1/tenants/{id}/summary` (organization name, caller's effective role and cap, `via_agency`) under a new permission `org.summary` held by every role incl. agency; still no `org.read` or other `org.*` for agency; added to PR C. (2) Location filters are a separate PR D (inbox, contacts, knowledge, analytics, channels query sites; then remove the `LOCATION_SCOPE_UNSUPPORTED` refusal); until PR D merges, PR C must not expose any way to assign `limited` scope (team UI/API keep it disabled) and the flag stays off. (3) Deviations accepted: grant locations as a join table, stored `editor` is the Agent alias, a direct membership wins over an agency grant.
- (History, done) Phase 3 order: PR C is implemented on `phase-3/identity-impl-c` (draft PR, stacked on B); the owner reviews A (#6), B (#7) and C and merges them together (A, then B, then C); then PR D (location filters, plan first). Do not start PR D before the owner says C was reviewed.
- CI: GitHub Actions is paused for billing; the SaaS workflow `.github/workflows/saas-ci.yml` has never run.

## Decisions needed
- **Phase 3 design decisions D1 to D10** are listed in the summary of `docs/IDENTITY-DESIGN.md` (Instagram for client users and the frozen-file list, exposure of the SSO exchange endpoint, email provider, client rights on knowledge/bots, role set, password-hash carry-over, duplicate-email rule, MFA and session lifetimes, first staff and Owner accounts). D1 is a STOP-and-ask item for frozen Instagram code; no edit is proposed.
- (Resolved by owner 2026-11-24: patch approved with single-label entries; accepted trusted compose-DNS boundary; transport pinning deferred to Phase 6.) Allowlist design review: accept the documented owner-controlled compose DNS boundary for Many (its existing validator and HTTP client resolve separately), or authorize a separate transport-pinning design. The proposal retains production HTTPS and gives each side only its one outbound service hostname. Empty preserves legacy behavior; enabled policy rejects case/trailing-dot variants rather than granting aliases. Docker engine remains unavailable on all three design-session `docker info` checks; recheck before any container operation.
- Phase 2 blocker: `modules/saas/apps/api/app/channels/outbound.py::resolve_target` rejects every non-global resolved address in every environment. Replies to a compose service name therefore fail even in tests. Many's `saas_delegation_service.validate_base_url` also rejects private targets in production. Internal signed calls cannot meet the approved requirements with application code unchanged. Owner decision required on a narrowly scoped internal-service allowlist/security design and the application-code exception; any shared Many changes affecting Instagram need explicit frozen-code approval. Do not bypass these guards in the mock harness or disable production protections.
- Previous owner decision: tests move to Linux (Phase 1b); no relocation of venvs / node_modules on Windows; Application Control policy left alone.

## Open choices
- SaaS Next 16 as dashboard shell [default yes]
- Postgres 15 and 17 kept separate at first [default yes]
- End customers get no login [to confirm]
- Instagram code touched only with OK each time [agreed]

## Open items outside the plan
- (Owner) Revoke the old Meta token at Meta (the file was removed from the imported history; the token itself is still valid until revoked).
- (Owner) The token file also held a webhook secret and a verify token: rotate them in a planned window together with the apps' settings. Not part of Phase 1; no live system was touched.
- Fix stale note in Many CLAUDE.md (migration head says 0022, real head is 0030); copy kept at `docs/legacy/many-CLAUDE.md`.
- `git-filter-repo`, `pg_ctl.exe`, `pg_isready.exe` and compiled files in venvs under `%TEMP%` are blocked by this machine's Application Control policy (affects tooling, not the repo).
- Many `requirements.txt` is unpinned (0 of 18 lines pinned); the SaaS uses lock files. Candidate for Phase 2.
- Root `.gitignore` does not ignore a root-level `.env.local` (only `dashboard/.env.local`).

## Last session
- 2026-11-26 (Phase 4 step 4E), Claude Code in a cloud container (Node 22, Postgres 16, no Docker daemon): built the identity screens (plan section 16): sign-in second step, password reset, invitation without an account, two-step verification and devices on Account, team screen v2, plus `identity_v2` in `auth/config` (only while the flag is on). Web lint and typecheck clean, 93 unit tests, 15 browser tests with faked answers and 3 against the real API with identity v2 on; full web suite 293 passed, 0 failed, 3 skipped (the flagged real-API spec). No migration, no Many or Instagram file changed. Not done: locations and agencies screens, QR code, real authenticator code sign-in, real email. Next: owner review of 4A to 4E, then the 4F plan.
- 2026-11-26 (Phase 4 steps 4C and 4D), Claude Code in a cloud container (Node 22, Postgres 16, no Docker daemon): built the client pages (channels, Facebook campaigns, WhatsApp, public opt-in with a new unauthenticated proxy route, `/accounts` return page) and the staff pages (Instagram accounts and campaigns, leads, messages, logs, conversations), menu, redirects and titles (plan section 15). Four agents ported pages on separate files; I integrated and ran every spec. Web: lint, typecheck, CSS check clean; 87 unit tests; full Playwright suite 278 passed, 0 failed; SaaS opt-in route 17 tests (65 with the proxy tests); ruff, format, mypy clean; frozen-Instagram check OK. Not done or not run: Meta connect flows (stubbed), real Many behind pages, Node 24, dev-up, nginx, mobile, RTL, screenshots; Many must be started with `--proxy-headers` before the public opt-in call is used (runbook). No migration, no Instagram or Many file changed. Left in this container only: Postgres on 127.0.0.1:5439, venvs, `node_modules`, `.next`, test-results. Next: owner review of 4A to 4D, then the 4E plan.
- 2026-11-26 (Phase 4 step 4B), Claude Code in a cloud container (Node 22, Postgres 16, no Docker daemon): implemented the shell (plan section 14). Web: lint, typecheck, build clean; unit tests 33 passed; new Playwright spec 9 passed; full web Playwright suite 184 of 185 on the last run (the one failure, a 30 s timeout in `ui-characterization`, passed twice on re-run). Existing tests changed: badge text, single-organization switcher, fixture for `/summary` (14.2). No API, Many, Instagram or migration change. Not run: Node 24, dev-up, nginx, real Many behind the page, mobile or RTL screenshots. Noted: `next build` stops once per session with a Next 16.4.3 security notice; the upgrade was not run. Left in this container only: Postgres on 127.0.0.1:5439 and unix socket `/var/tmp/p4pg`, Redis state, venvs, `node_modules`, `.next`. Next: owner review of 4A and 4B, then the 4C plan.
- 2026-11-26 (Phase 4 step 4A), Claude Code in a cloud container (Postgres 16, Redis and Python installed from apt or pip into ignored scratch; no Docker daemon, Node 22): recorded P1 to P8, implemented 4A (plan section 13). Many 1292 passed; SaaS 1539 passed and 10 failed, the same 10 as a clean origin/main (pgvector 0.6.0 lacks `hnsw.iterative_scan`); script tests 61 passed; ruff, format and strict mypy clean; frozen-Instagram, policy and contract checks OK. Not run: `dev-up.sh test`, nginx edge checks, web gates, Playwright. No migration, no Instagram file, nothing merged or deployed. Left in this container only: throwaway Postgres clusters under `/var/tmp`, a loopback Redis, venvs and `node_modules` in ignored paths. Next: owner review of 4A, then 4B (plan first).
- 2026-11-26 (Phase 4 step 1), Claude Code in a cloud container (no Docker daemon, Node 22, Python 3.12, no project dependencies): merged `docs/phase-4-plan` (fast-forward), read both frontends, the Many route guards, the SaaS shell and the identity docs, wrote `docs/UI-INVENTORY.md` and the design (PHASE-4-PLAN section 12). Only docs changed. Nothing was run or tested; `npm ci --ignore-scripts` was run in `modules/saas` (ignored files) to look for the Next 16 docs, which were not there. New gaps 9 to 13 are read from code and untested. Next: owner review and P1 to P8; then 4A (one branch, plan first).
- 2026-11-26 (Phase 4 planning), Claude Code: wrote `docs/PHASE-4-PLAN.md`, replaced the Phase 4 prompt in `docs/PHASE-PROMPTS.md`, added a pointer in `docs/MERGE-PLAN.md` (branch `docs/phase-4-plan`, docs only; gaps found by reading code, no tests run, no application code changed). Next: Phase 4 step 1, planned in a cloud session cloned from GitHub (see PHASE-4-PLAN section 9). Noticed: the GitHub repository is public, although Phase 0 called for a private one (owner to decide).
- 2026-11-26 (Phase 3 review and merge), Claude Code on WSL + Docker: reviewed PRs #6 to #9, wrote failing tests, fixed findings 1 to 9 on `phase-3/review-fixes`, ran the gates in `docs/PHASE-3-REVIEW.md` (SaaS 1491, Many 1286, scripts 50, nginx 75/75, six e2e PASS), opened the review PR and merged the stack with the owner's approval. No deploy, no live systems. Local leftovers: stopped containers `phase3-pg15` and `phase3-pg17`, WSL `~/phase3/`, `unified-*` images, session scratchpad scripts. Next: Phase 4 step 1.
- 2026-11-25 (Phase 3 PR D), Claude Code on WSL + Docker: implemented location filters and scope assignment on `phase-3/identity-impl-d`, gated as above, pushed, opened the draft PR. Stopped for review; nothing merged. Full suite not re-run after the last two commits.
- 2026-11-25 (Phase 3 PR C), Claude Code on WSL + Docker: reviewed PRs #6 and #7, fixed the five nits, implemented PR C commits (a) to (h) on `phase-3/identity-impl-c`, ran the end-of-PR gate (table above), pushed, opened the draft PR. Stopped for the owner's review; PR D not started. Nothing merged. Local leftovers: containers `phase3-pg15` and `phase3-pg17`, WSL `~/phase3/` (snapshot, results), the rebuilt `unified-*` images, session scratchpad scripts (outside the repo). The unified e2e stack was torn down by `dev-up.sh test`.
- 2026-11-25 (Phase 3 PR B), Claude Code on WSL + Docker: branch `phase-3/identity-impl-b` from the PR A head (PR #6 still open, `main` unchanged at the #5 merge). SaaS migrations 0032 to 0034, models, `app/identity/{roles,locations,agency,access}.py`, flagged `TenantContext` permission checks, route-permission map, 32 new tests (results table above). Stopped before PR C, awaiting owner review. Local leftovers: containers `phase3-pg15` and `phase3-pg17`, WSL `~/phase3/` (snapshots, results). A stale socket bridge had to be cleared after the WSL restart.
- 2026-11-24 (Phase 3 PR A), Claude Code on WSL + Docker: PR #5 merged by the owner's approval; implemented commits 1 to 7 of the identity plan on `phase-3/identity-impl-a` (results table above). Stopped before PR B, awaiting owner review. Local leftovers: Docker containers `phase3-pg15` and `phase3-pg17` (ports 55415 and 55417), WSL `~/phase3/` (clone `repo`, snapshots, results logs, harness scripts), the rebuilt `unified-*` images.
- 2026-11-24 (Phase 3 design), Claude Code, cloud container without Docker or installed Python dependencies: created branch `phase-3/identity-design` from `origin/main` (`cc3b9ab`); wrote `docs/IDENTITY-DISCOVERY.md` and `docs/IDENTITY-DESIGN.md`; updated this file. Observed: Alembic heads read from the files (Many `0030_meta_account_erasure`, SaaS `0031_contact_erasure`, one head each); `scripts/check_policy_copies.py` OK; `scripts/check_contract_copies.py` (Many root) OK; the SaaS-root contract check was not run (my `--root modules/saas` guess failed because the manifest is under the repo-root `docs/`). Test baselines NOT verified here (no dependencies); numbers above are from the Phase 2b gate. Only docs files changed. Nothing merged.
- 2026-11-24 (PR #4 review follow-up), Claude Code: tested mixed-case paths through nginx: `/API/channels/...` and `/Api/channels/...` on the SaaS web host reached the signed events handler (401 from its signature check); the other hosts did not. Added case-insensitive `~*` deny locations (both SaaS hosts, Many `/api/saas`), 7 new edge checks (48 total, 48 pass), six e2e cases pass, `default.conf` untouched; Redis auth added to the DEPLOY-OUTLINE hardening list. Details in `docs/PHASE-2-RESULTS.md` 4.6. Local state: unified-e2e stack left running (KEEP=1); cleanup still on hold.
- 2026-11-24 (Phase 2b), Claude Code: PR #3 merged; implemented Phase 2b locally (see In progress and the gate table). Network to GitHub was down for pushes; nothing pushed from the 2b branch. Old local commit `cad31e5` (progress wording for the PR #3 review) is superseded by this text and is not cherry-picked.
- 2026-11-24 (later), Claude Code: owner follow-up. Re-ran the full SaaS suite (1277/0, see table) and the six e2e cases (all PASS, saved in `docs/PHASE-2-RESULTS.md`), added the approved CI workflow `phase2-policy-copies.yml` (policy copies + both contract-copy checks, paths filter includes contract docs), audited the remaining Phase 2 scope (statuses in the PR comment/report; nothing started). Local state left for owner OK: p2e2e stack running, merge-dev DB containers started again, images, WSL scratch.
- 2026-11-24, Claude Code: implemented the approved allowlist on `phase-2/one-infrastructure` (results table above). Added `docker-compose.phase2-e2e.yml` and `e2e/phase2/` (mock Meta, throwaway CA, per-run random fake secrets, internal-only network), `scripts/check_policy_copies.py`, and 61 tests per side. Security review run in-session. Stopped with Docker Desktop not running; the r19 re-run and any compose step are pending. CI workflow file proposed to the owner, not added. Local leftovers from this session: `p2e2e-*` images, `merge-dev-*` containers if still present, WSL `~/phase2/` scratch and socket bridges.
- 2026-11-23, Codex (docs-only handoff): owner requested committing and pushing only this progress record, the allowlist design and the unapplied proposed patch on `phase-2/one-infrastructure`, with no PR, tags or force-push. Application implementation remains unapproved; next step is owner review of the design and DNS trust-boundary decision.
- 2026-11-23, Codex (design follow-up): produced only the allowlist design and unapplied diff above, plus this progress update. Verified all seven proposed Python targets parse, `git apply --check` succeeds, and working-tree diff under application paths is empty. No application implementation, pytest, security review, workflow creation, container operations, push or PR. Await exact design/diff approval; the requested post-implementation security review remains pending.
- 2026-11-23, Codex: Phase 2 preflight stopped on the internal-address guards above. Current feature branch starts at main `8450ae5`; only this progress record changed. `git fetch origin main` succeeded; both supplied merge commits verified locally. Saved freeze `/home/youssef/phase1b/venvs/many-freeze.txt`: 68 packages, MD5 `4c30f8edc6ffa514c5e3c7e2237be481`, SHA256 `49c4c703ecc08ea606a113815ffc8872b4b9ccf17b74ba7aa51d37dc10a7aa45`; both saved Many venv freezes have the identical MD5, matching PHASE-1B-RESULTS. `python -m pip freeze` was unavailable in the uv-managed venv (no pip); verification succeeded with `uv pip freeze --python ...`. Docker CLI is installed but Docker Desktop engine was unavailable and WSL reported Docker integration unavailable; no containers, volumes, migrations, tests, API calls, push, or PR created. Next: resolve the internal-service policy exception, restore Docker availability, then continue the approved Phase 2 work and show all workflow files for approval before adding them.
- 2026-11-23, Claude Code: Phase 1b verification (branch `phase-1b/verification`). All results in `docs/PHASE-1B-RESULTS.md`. Stopped before Phase 2.
- Docker objects created by this session and removed: containers `merge-dev-pg15-1`, `merge-dev-pg17_vector-1`, `merge-dev-redis-1`; volumes `merge-dev_pg15_data`, `merge-dev_pg17_data`; network `merge-dev_default` (`docker compose down -v`). Pulled images (`postgres:15`, `pgvector/pgvector:pg17`, `redis:7-alpine`) were left in place.
- Scratch (outside the repo): WSL `~/phase1b/` (clones, venvs, results logs) and `~/tools/` (node 24.22.3, uv 0.13.9). Windows scratchpad from Phase 1 (incl. Postgres data dir) untouched.
- Findings for later phases: (1) Many tests assume a local-socket Postgres under /var/tmp or /tmp and DB name `many_test_r1`; (2) one SaaS test needs `PGHOST` socket + `ENVIRONMENT=test`; (3) a SaaS test rewrites tracked `implementation/PHASE-03/EVAL-REPORT.md`; (4) SaaS web `format:check` fails on 4 files in the original too.
