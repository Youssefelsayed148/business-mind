# Phase 6, step 6.0: readiness (owner checklist)

Status: **OPEN. Written 2026-11-28; every result cell below is empty because nothing in it has been run by me.** The plan is `docs/PHASE-6-PLAN.md` (approved 2026-11-28, D1 to D10 as recommended, PR #14 merged). Step 6.0 closes the gates carried over from Phases 4 and 5. They need Docker, nginx, Postgres 15 and 17 and a restored copy of data, none of which exist in the cloud container, so you run them and send me the output. I then fill the Result column, update the progress files and close 6.0.

Rules: throwaway databases only (`APP_ENV=test`, `TEST_DATABASE_URL` set explicitly, print host and name first); never a live database; no real Meta or OpenAI. Run from the repo root in WSL.

## A. Gates (Phase 4 and 5 leftovers)

| # | Gate | Command | Pass means | Result |
|---|---|---|---|---|
| A1 | Unified stack end to end | `scripts/dev-up.sh test` | six mock channel cases PASS, edge checks PASS, stack torn down | |
| A2 | Edge deny incl. `/auth/sso/exchange` | `e2e/phase2/check_nginx.py` (runs inside A1; run alone against a started stack if A1 fails) | 15 spellings of the exchange denied (403, `X-Edge-Deny: 1`), not denied on the SaaS hosts, `/auth/login` not shadowed | |
| A3 | Many backend suite | `cd backend && python -m pytest tests -q -p no:cacheprovider -rfEs` on Postgres 15 | baseline 1084 passed (Phase 2b), no new failure | |
| A4 | SaaS backend suite | `cd modules/saas/apps/api && python -m pytest -q -p no:cacheprovider -rfEs` on Postgres 17 with the real pgvector | all pass. In the cloud container 10 pgvector 0.6.0 tests failed (embedding readiness 3, hybrid retrieval 4, r19 index 1, RAG evaluation 2); they should pass on pgvector 0.7 or newer. Report any failure by name | |
| A5 | Script tests | `python -m unittest discover -s scripts -p "test_*.py"` (and the two Many script suites you used in Phase 1b) | all OK. Run it inside Many's Python 3.11 environment with its dependencies installed and a throwaway Postgres: here, with plain system Python, 26 of 29 ran OK and 3 errored on missing `sqlalchemy` and `fastapi` (an environment gap, not a code result) | |
| A6 | Copy and freeze checks | `python scripts/check_policy_copies.py`, `python scripts/check_contract_copies.py`, `python scripts/check_instagram_frozen.py` | OK, OK, OK | |
| A7 | Web on Node 24 | in `modules/saas/apps/web`: `npm run lint`, `npm run typecheck`, `npm test` (Playwright) | lint and typecheck clean; Playwright baseline 306 passed, 0 failed, 3 skipped | |
| A8 | Old dashboard walk | open the Many dashboard on the unified stack, visit each page once, note anything that differs from the old deployment | list of differences, or "none" | |
| A9 | Phase 5 on the real Many | with a throwaway Many and the SaaS API, `DATA_UNIFICATION_ENABLED=true`: one staff sync, one erasure of a test lead, check Many answers `local_status: "erased"` | sync creates links, second run changes nothing, erasure case reaches `complete` | |

If a gate fails: paste the failing test names and the last 40 lines. I fix and you re-run that gate only.

## B. Restored-copy link check (Phase 5 exit criterion)

Steps are in `docs/DATA-UNIFICATION.md` section 18 (dry run, real run, second run changes nothing, duplicates query returns no rows, counts, conflicts, elapsed time). Needs restored copies of both live databases on a throwaway stack. Send me: the three JSON answers (`created`, `updated`, `ignored_leads`, `by_state`), the duplicates query result, the counts query result and the elapsed time of the dry run.

| Item | Result |
|---|---|
| Dry run `created` / `ignored_leads` / `by_state` | |
| Second real run `created` and `updated` (must be 0) | |
| Duplicates query rows (must be 0) | |
| `conflict` rows | |
| Dry run elapsed time | |

## C. Decisions to confirm (Phase 5 design changes)

Say "confirmed" or what to change, for each (`docs/DATA-UNIFICATION.md` sections 14, 16, 17):

1. The raw external id stays on the link row until an erasure completes.
2. Instagram channels are owned through staff claims (Many's account list names no workspace).
3. "Costs" means SaaS bot usage only; Many has no costs or per-organization message counts.
4. "Complete" means Many reported its local erase.
5. Erasing one identity deletes the SaaS contact; other-channel links stay until each is erased.
6. The Many part of the combined audit is global and staff-only.

## D. Owner actions that are not code (D8 and D10 of the plan)

- D10: make the GitHub repository private before staging holds any real configuration (Settings, General, Danger Zone). I have no tool for this.
- D8: restore GitHub Actions billing if affordable; otherwise the local gates above stay the gate before every merge.
- D6: choose the staging server provider and size (needed by 6B, not by 6.0).
- D3: send current peak traffic numbers (webhooks per minute, dashboard users) for 6F.

## E. Done when

A1 to A9 and B have results with no unexplained failure, C is answered, and I have recorded the outputs in `docs/PHASE-4-PLAN.md` section 17, `docs/DATA-UNIFICATION.md` section 19 and `docs/MERGE-PROGRESS.md`. A gate you cannot run is recorded as "not run, reason", never as passed. Phase 4 and Phase 5 are then closed.

## F. Change log

- 2026-11-28, Claude Code: checklist written from the Phase 4F, 5F and Phase 1b records. Nothing run.
