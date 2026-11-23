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
- Phase 1 task 6 (test runs in new repo vs originals): **BLOCKED, not run.** Application Control blocks compiled
  extensions (e.g. SQLAlchemy `_immutabledict_cy`) in the venv created under the scratch folder in `%TEMP%`.
  No test result exists yet for either suite. SaaS DB-backed API tests will be NOT RUN regardless (no pgvector:
  no C compiler, not admin, PG17 extension dir not writable). Many on this machine: PG 17 (not 15), no Redis.
- Draft PR: not opened yet (waiting for the test decision).

## Next
- Decide how to run the suites (see "Decisions needed"), run baselines and new-repo suites, record exact results.
- Then: push `phase-1/foundation`, open a DRAFT PR, final Phase 1 report.
- Phase 2: One infrastructure (also: re-home SaaS CI from `modules/saas/.github/`, which is inactive; the SaaS has no CI here until then).

## Decisions needed
- Where may the Python venvs / Node dependencies live so that Application Control allows their compiled files?

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
- 2026-11-23, Claude Code: Phase 1 import done and committed locally on `phase-1/foundation`; nothing pushed; tests blocked as above.
