# Phase 6G: fixes for the open Phase 3 review items (SaaS side)

Scope: `docs/PHASE-3-REVIEW.md`, "Open before enabling any flag", items 1 to 3, 6 and 7.
All identity flags stay default off. No Instagram code touched. Synthetic data, throwaway
Postgres 16 (`/var/tmp/p4pg`, database `saas_p4_base_test`, `ENVIRONMENT=test`).

## Finding: items 1, 3 and 7 were already fixed in Phase 4A

The review list was stale. Commits `e14aee4` (item 1) and `b52fd5c` (items 3 and 7) already
contain the fix and the regression tests. This session only re-proved the tests:
the app changes of those two commits were reverse-applied, the tests run, then restored.

| Item | Fix (already on the branch) | Tests |
|---|---|---|
| 1 TOTP/recovery reuse race | `mfa.verify_second_factor` takes the `user_mfa` row with `FOR UPDATE` | `tests/test_mfa.py::test_a_recovery_code_cannot_be_spent_twice_at_once`, `::test_a_totp_code_cannot_be_used_twice_at_once` (4 threads, own sessions) |
| 3 limited Admin and org-wide settings | `require_every_location()` on retention PATCH and change-request list, create, download; answer is 403 `FORBIDDEN` (not `LOCATION_SCOPE_UNSUPPORTED`; same helper as knowledge and team routes) | `tests/test_phase4a_fixes.py::test_a_location_limited_admin_cannot_use_organization_wide_settings[retention, list_change_requests, create_change_request]` |
| 7 Admin replaces pending Owner invite | `team.invite` calls `_require_may_edit` on each pending invitation (403 `OWNER_REQUIRED`) | `tests/test_phase4a_fixes.py::test_an_admin_cannot_replace_a_pending_privileged_invitation[owner, admin]` |

With those app changes reversed: 8 failed, 18 passed (the three race tests, the five 4A tests,
plus one MFA login test that depends on the lock). Restored: all pass.

## New in 6G

**Item 2, limited grant must fail closed.** A grant's reach was "all locations" when it had
no location rows, so deleting its last location (FK cascade) would widen it.
- `alembic/versions/0038_grant_location_scope.py` (additive): `agency_grants.location_scope`
  `'all'|'limited'`, default `'all'`, backfill `'limited'` where location rows exist. Downgrade
  drops the column and its check.
- `app/db/models/identity.py`, `app/identity/agency.py`: `create_grant` stores the scope;
  `active_grant_for` returns the (possibly empty) set for a limited grant, `None` only for `all`;
  an empty limited grant sorts as the narrowest. `location_filter` already turns an empty set into
  "match nothing".
- Test: `tests/test_phase6g_fixes.py::test_a_limited_grant_with_all_locations_deleted_denies`
  (control: `::test_an_unrestricted_grant_stays_unrestricted`).
- `tests/test_identity_migrations.py`: head is now `0038_grant_location_scope`; chain slice
  shifted by one (intended).

**Item 6, older invitation route.** With identity v2 on, `POST /api/v1/tenants/{id}/invitations`
no longer answers 404 `USER_NOT_FOUND` for an unknown address; it creates an invitation for a
new account (`new_account=true`, as the team route does) and answers 201 like for a known one.
Flag off: unchanged (`tests/test_staff_members.py` still expects `USER_NOT_FOUND`).
Files: `app/tenants/router.py`, `app/tenants/service.py`.
Test: `tests/test_phase6g_fixes.py::test_older_invitation_route_gives_one_answer_for_known_and_unknown_addresses`.
Remaining signal: an existing active member still gets 409 `ALREADY_MEMBER` (an admin can see
the member list anyway).

Both new behaviour tests fail with the app changes reversed (2 failed, control passed).

## Needs owner decision (no behaviour changed)

- 4: agency users cannot take over or reply (schema needs a membership row).
- 5: unrestricted agency Admin can export and read the audit log.
- 8: never run `scripts/identity_migrate.py apply` on real data.
- 9: SSO exchange takes over or removes a local Many membership; back up first.
- 10: invitation links handed over by the inviter until an email provider is chosen (D4).
- 11: configure `real_ip` if a TLS terminator or CDN is added in front of nginx.

## Checks

See the final report of the session for the full-suite numbers and tool output.
`ruff check` clean. `ruff format --check` and `mypy` report only pre-existing issues in files
this work did not touch (`alembic/versions/0037_erasure_cases.py`; four `tests/test_customer_*` and
`test_combined_audit.py` files).
