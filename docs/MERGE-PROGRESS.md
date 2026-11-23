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
- **Phase 2 allowlist DESIGN ONLY (2026-11-23, Codex)**: owner authorized a design, not implementation. Exact design and unapplied seven-file application/test patch are in `docs/design/INTERNAL-SERVICE-ALLOWLIST.md` and `docs/design/internal-service-allowlist.proposed.patch`. Proposed Python syntax and `git apply --check` pass; no proposed tests executed. No application, frozen code, call sites, contract or workflow files changed. Await owner review of the patch and the explicit Many DNS trust-boundary limitation.
- **Phase 2 preflight (2026-11-23, Codex), branch `phase-2/one-infrastructure`**: created from main at `8450ae5` after verifying merge commits `047ba53` and `8450ae5` (two parents each), Phase 1b ancestry, Many/SaaS history counts 114/457, and empty `git log --all -- "popeye access token.txt" dashboard/.env.local`. Implementation stopped at the internal-network security-policy conflict below; no application or workflow changes.
- **Phase 1b (verification) done on branch `phase-1b/verification`**: for every suite present in both trees the merged repo equals the original; see `docs/PHASE-1B-RESULTS.md` (draft PR against `phase-1/foundation`).
- Phase 1 exit criteria: history yes; suites match originals yes (with the caveats in PHASE-1B-RESULTS); draft PR #1 yes; no secrets yes. Pending: owner review/merge of PR #1 and the Phase 1b PR.

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

## Next
- Review/merge PR #1 and the Phase 1b PR (owner).
- Phase 2: One infrastructure (also: re-home SaaS CI from `modules/saas/.github/`, which is inactive; the SaaS has no CI here until then).

## Decisions needed
- Allowlist design review: accept the documented owner-controlled compose DNS boundary for Many (its existing validator and HTTP client resolve separately), or authorize a separate transport-pinning design. The proposal retains production HTTPS and gives each side only its one outbound service hostname. Empty preserves legacy behavior; enabled policy rejects case/trailing-dot variants rather than granting aliases. Docker engine remains unavailable on all three design-session `docker info` checks; recheck before any container operation.
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
- 2026-11-23, Codex (docs-only handoff): owner requested committing and pushing only this progress record, the allowlist design and the unapplied proposed patch on `phase-2/one-infrastructure`, with no PR, tags or force-push. Application implementation remains unapproved; next step is owner review of the design and DNS trust-boundary decision.
- 2026-11-23, Codex (design follow-up): produced only the allowlist design and unapplied diff above, plus this progress update. Verified all seven proposed Python targets parse, `git apply --check` succeeds, and working-tree diff under application paths is empty. No application implementation, pytest, security review, workflow creation, container operations, push or PR. Await exact design/diff approval; the requested post-implementation security review remains pending.
- 2026-11-23, Codex: Phase 2 preflight stopped on the internal-address guards above. Current feature branch starts at main `8450ae5`; only this progress record changed. `git fetch origin main` succeeded; both supplied merge commits verified locally. Saved freeze `/home/youssef/phase1b/venvs/many-freeze.txt`: 68 packages, MD5 `4c30f8edc6ffa514c5e3c7e2237be481`, SHA256 `49c4c703ecc08ea606a113815ffc8872b4b9ccf17b74ba7aa51d37dc10a7aa45`; both saved Many venv freezes have the identical MD5, matching PHASE-1B-RESULTS. `python -m pip freeze` was unavailable in the uv-managed venv (no pip); verification succeeded with `uv pip freeze --python ...`. Docker CLI is installed but Docker Desktop engine was unavailable and WSL reported Docker integration unavailable; no containers, volumes, migrations, tests, API calls, push, or PR created. Next: resolve the internal-service policy exception, restore Docker availability, then continue the approved Phase 2 work and show all workflow files for approval before adding them.
- 2026-11-23, Claude Code: Phase 1b verification (branch `phase-1b/verification`). All results in `docs/PHASE-1B-RESULTS.md`. Stopped before Phase 2.
- Docker objects created by this session and removed: containers `merge-dev-pg15-1`, `merge-dev-pg17_vector-1`, `merge-dev-redis-1`; volumes `merge-dev_pg15_data`, `merge-dev_pg17_data`; network `merge-dev_default` (`docker compose down -v`). Pulled images (`postgres:15`, `pgvector/pgvector:pg17`, `redis:7-alpine`) were left in place.
- Scratch (outside the repo): WSL `~/phase1b/` (clones, venvs, results logs) and `~/tools/` (node 24.22.3, uv 0.13.9). Windows scratchpad from Phase 1 (incl. Postgres data dir) untouched.
- Findings for later phases: (1) Many tests assume a local-socket Postgres under /var/tmp or /tmp and DB name `many_test_r1`; (2) one SaaS test needs `PGHOST` socket + `ENVIRONMENT=test`; (3) a SaaS test rewrites tracked `implementation/PHASE-03/EVAL-REPORT.md`; (4) SaaS web `format:check` fails on 4 files in the original too.
