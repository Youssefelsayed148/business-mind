# Phase 3 review (PRs #6 to #9)

Date: 2026-11-26. Reviewer: Claude Code. Scope: application code, migrations and edge
configuration of the stack `main` -> `phase-3/identity-impl-a` -> `-b` -> `-c` -> `-d`;
tests were sampled. Fixes are on `phase-3/review-fixes`, stacked on D.

Every finding below marked "Fixed" was first reproduced by a failing test on the D head
(28 failed, 11 passed in `test_phase3_review_fixes.py` and `test_role_matrix.py`; the two
nginx tests failed against the old `unified.conf`).

## Verdict

PRs A to D plus the fixes can merge. All identity flags stay **off**. Do not enable a flag
before the items under "Open before enabling any flag" are decided.

## Findings fixed

| # | Severity | Finding | Fix |
|---|---|---|---|
| 1 | High | With identity v2 on, the older `/members` and `/invitations` routes skipped the team rules: an Admin could remove the Owner, invite an Admin, or resend an Owner invitation and receive its link; a location-limited Admin could escape their scope. | The routes apply the team rules (`app/identity/team.py`). Flag off: unchanged. |
| 2 | High | `org_role` (filled by migration 0034) overrides `role`, but older writers changed only `role`, so demotions and re-adds could be ignored. | Older writers clear `org_role`; they can no longer demote or remove the last Owner. |
| 3 | High | A location-limited Admin could export the whole organization and read its audit log. | Both need access to every location. |
| 4 | High | Agency users got HTTP 500 on routes with a legacy role check, and the live inbox closed at once. | The legacy check follows the effective role; the stream re-checks the grant on every poll. Agency exports leave out members and invitations. |
| 5 | Medium | D5 (clients edit knowledge) did not work: handlers still required staff. | Owner, Admin and Manager may write, if their access covers every location. Bot and retrieval settings stay staff-only. |
| 6 | Medium | `/api/auth/sso/exchange` reached the exchange without the edge rate limit. | Same limit on every spelling (`nginx/unified.conf`). |
| 7 | Medium | A forged `X-Forwarded-For` reset the SaaS per-address limits. | The SaaS vhosts overwrite the header with the peer address. |
| 8 | Medium | Contact export failed above 65,535 contacts, **also with the flag off** (introduced on this stack). | Subquery instead of one bind parameter per contact. |
| 9 | Medium | An Owner could reset the MFA of platform staff or of people who belong to other organizations. | Staff only for those accounts and for agency people. |

The role matrix test now also fails when an allowed role gets a 500 or an older refusal
message, and it covers every agency cap on every tenant route. That gap is why findings 4
and 5 passed before.

## Open before enabling any flag

1. Two simultaneous requests can use the same TOTP or recovery code (rows are not locked).
2. A location-limited agency grant would become unrestricted if all its locations were
   deleted. No API deletes locations today.
3. A location-limited Admin can still change the organization's retention setting and
   create or read change requests.
4. Agency users can read the inbox but cannot take over or reply, whatever their cap: the
   database requires a membership row for those columns. The design allows replies for an
   Agent cap; decide whether to change the design or the schema.
5. An unrestricted agency Admin can export contacts and conversations and read the audit
   log, which includes team events. This follows the design's permission names; confirm.
6. The older invitation route still says whether an account exists (to team admins only).
7. On the new team route an Admin can replace a pending Owner invitation for the same
   address with a lower one.
8. Do not run `scripts/identity_migrate.py apply` against real data: it disables linked
   users' Many passwords while the Many dashboard has no SSO.
9. An SSO exchange takes over a local Many membership, and a later exchange for another
   organization removes it (design 5.4). Back up first.
10. Until an email provider is chosen (D4), invitation links are handed over by the
    inviter, so the inviter can create the invitee's account.
11. If a TLS terminator or CDN is put in front of nginx, configure `real_ip` there, or all
    clients share one rate-limit address.

## Not built in Phase 3

The merge plan's exit line "one login reaches every page" is **not** met end to end:

- No web screens for team, invitation acceptance, password reset or MFA, and the Many
  dashboard does not use SSO.
- Nothing writes the organization to workspace mapping (`tenants.many_workspace_id`,
  `workspaces.saas_tenant_id`), and the migration script does not create memberships.
- No API creates locations or agencies.

These are carried into Phase 4 planning.

## Gates on the final code

WSL + Docker, throwaway databases, test runs in a network namespace without external
access, GitHub Actions paused.

| Gate | Result |
|---|---|
| SaaS full suite (`saas_p2_full_test`) | 1491 passed, 4 warnings, 25 min 5 s |
| Many full suite (`many_test_r1`) | 1286 passed, 3 warnings, 2 min 45 s |
| Repo script tests (`many_test_scripts`) | 50 passed, 25 subtests passed |
| ruff check, ruff format, mypy (`app tests alembic`) | clean (331 files type-checked) |
| Frozen Instagram, policy copy, both contract copy checks | OK |
| `scripts/dev-up.sh test` (images rebuilt from this branch) | six e2e cases PASS, nginx 75/75 |

About the end-to-end gate: the first three attempts failed during image builds on network
errors (Docker Hub lookup and login, then a PyPI download). The first run that reached the
tests passed the six cases and 71 of 73 nginx checks; the two failures were new checks that
ran after earlier checks had used up the shared rate-limit allowance. The checks now wait
for it to refill, two spellings were added, and the full command was run again with
`NO_BUILD=1` on the same images.

Not run: SaaS web and Many dashboard lint, type check and build (no frontend file changed
by the review fixes), and a load test.
