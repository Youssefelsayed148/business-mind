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
- **Phase 2 = DONE: PR #3 merged into main (`940e74a`).** Independent review found no blockers and three low items, all handled in Phase 2b: (1) mixed DNS answers for a listed host now fail closed (commit `ddb4051`); (2) RUNBOOK-DEV documents that `CHANNEL_INTERNAL_ALLOWED_HOSTS` is whitespace- and trailing-comma-sensitive and that invalid values fail startup; (3) `docs/PHASE-2-RESULTS.md` states that the e2e runs in development over http, so the production-HTTPS rule is covered by unit tests only. Security notes remain binding: not full SSRF parity, trusted compose-DNS boundary, Many double DNS resolution (transport pinning = Phase 6, owner approval needed), allowlist is deployment config only. Phase 6 candidates: Many transport pinning; optional `host:port` allowlist entries; PR trigger for the SaaS CI.
- **Phase 2b = IN PROGRESS, branch `phase-2b/unified-compose` (draft PR to be opened after the owner allows the push), 2026-11-24.** Implemented locally: unified compose (`docker-compose.unified.yml`, no-egress `docker-compose.unified.e2e.yml`, prod overlay `docker-compose.unified.prod.yml` written and never deployed), `nginx/unified.conf` (deny of Many's signed `/api/saas/*` and `/saas/*` and of SaaS `/api/channels/*` on both SaaS hosts; `nginx/default.conf` untouched), `.env.unified.example` (placeholders only), `scripts/dev-up.sh` (up|test|down), `backend/constraints.txt` (MD5 `4c30f8ed…` matches the freeze; no index URLs or credentials), `docs/RUNBOOK-DEV.md`, `docs/DEPLOY-OUTLINE.md`, edge checks `e2e/phase2/check_nginx.py`. Results: `docs/PHASE-2-RESULTS.md` section 4. SaaS CI workflow added as `.github/workflows/saas-ci.yml` (manual `workflow_dispatch` only, no secrets, `contents: read`; **never executed, Actions paused**; header lists the r19 deselect and the `format:check` continue-on-error). No push yet. **Owner decisions 2026-11-24:** keep the production HTTPS requirement (no relaxing); internal TLS with a private CA and edge TLS are **Phase 6 items, open**; the prod overlay stays written-not-deployable.
- **GitHub Actions is paused for billing: every gate stays local** (full suites in WSL, `scripts/check_policy_copies.py`, both contract checks, `scripts/dev-up.sh test`). The workflow `phase2-policy-copies.yml` ran once on PR #3 (pass) before the pause.
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

## Next
- Review/merge PR #1 and the Phase 1b PR (owner).
- Phase 2: owner review of the draft PR and the CI workflow proposal; then the remaining One infrastructure work (also: re-home SaaS CI from `modules/saas/.github/`, which is inactive; the SaaS has no CI here until then).

## Decisions needed
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
