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

## In progress
- **Phase 1 is incomplete.** Import, history proofs, docs, compose and secret scan are done; the test suites were NOT RUN.
- Draft PR open on `phase-1/foundation` (title starts "DRAFT: Phase 1 incomplete (test suites NOT RUN)").
- Phase 1b: verification (separate session, Linux environment, on the pushed branch). No more test runs on the Windows laptop.

### NOT RUN on the Windows laptop (no result exists for any of these; nothing was substituted)
| Item | Reason |
|---|---|
| Many backend pytest (original and new repo) | Application Control blocks compiled extensions (e.g. SQLAlchemy `_immutabledict_cy`) in a venv under `%TEMP%`; both runs exited 4 at import, 0 tests collected. Decision: no relocation of venvs to get around the policy. |
| Many tests that need Redis | No Redis on the machine (also Many targets Postgres 15; only 17.11 is installed here). |
| Many scripts unittest / dashboard tsc / dashboard lint | Not attempted (same Application Control / Node-modules constraint). |
| SaaS API pytest (all DB-backed tests) | Needs pgvector (migrations `CREATE EXTENSION vector`). Not installable here: no C compiler, not admin, PG17 extension dir not writable. |
| SaaS web lint and typecheck | Not attempted (node_modules install blocked by the same decision). Node on this machine is v26.13.0 vs the SaaS pin `>=24 <25`. |
| SaaS web Playwright e2e | Out of scope for Phase 1. |
| `docker-compose.merge-dev.yml` start-up | Docker daemon not running; only `docker compose config` (exit 0) was run. |

Reference baseline (not a result of this phase): Many's own record `docs/saas-delegation/many-full-test-evidence/README.md`
reports backend 1007 passed / 0 failed / 0 skipped on Postgres 15 + Redis (2026-10-29). Phase 1b must reproduce and compare, not assume.

## Next
- Phase 1b: on Linux with Postgres 15, Postgres 17 + pgvector and Redis: run Many backend, Many scripts/dashboard checks, SaaS API, SaaS web lint/typecheck, in the original repos (clean clones) and in this branch; compare and explain differences. Then mark Phase 1 exit criteria.
- Phase 2: One infrastructure (also: re-home SaaS CI from `modules/saas/.github/`, which is inactive; the SaaS has no CI here until then).

## Decisions needed
- (none open) Owner decided: tests move to Linux (Phase 1b); no relocation of venvs / node_modules on Windows; Application Control policy left alone.

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
- 2026-11-23, Claude Code: Phase 1 import done on `phase-1/foundation`, pushed with a DRAFT PR; test suites NOT RUN (list above). Stopped before Phase 1b.
- Scratch artifacts (outside the repo, nothing deleted): throwaway Postgres 17 data dir and baseline clones under the session scratchpad, see the final report for the path. The scratch Postgres was stopped.
- Owner check done: the JWT tail in `docs/saas-delegation/b2-evidence/*.log` is an elided fragment (no `exp` visible, no complete token): expiry cannot be determined from the file; it came from a test run with a fixture signing secret.
