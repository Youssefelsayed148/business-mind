# Phase 1b: verification of the Phase 1 import

Date: 2026-11-23. Branch under test: `phase-1/foundation` @ `32da29e74ba062c0cee07a5d21fb546e67ba2716` (PR #1).
This document and `docs/MERGE-PROGRESS.md` are the only changes on `phase-1b/verification`. No imported code was changed.

## Verdict

For every suite that exists in both trees, the merged repository gives **the same result as the original repository** in the same
environment. Many backend matches Many's own recorded baseline (1007 passed / 0 failed / 0 skipped). The module move
(`modules/saas/`) broke no path in any test, lint, typecheck or contract-copy check.

Honest caveats are in "Deviations and things to know" below (read them before relying on the numbers).

## Environment (same for original and new)

| Item | Value |
|---|---|
| Host | WSL2 Ubuntu 26.04.1 LTS, kernel 6.18.33.2-microsoft-standard-WSL2, on Windows 11 (Application Control does not apply inside WSL) |
| Postgres for Many | Docker `postgres:15` (15.19), `127.0.0.1:55415` |
| Postgres for SaaS | Docker `pgvector/pgvector:pg17` (17.11), pgvector extension 0.8.7, `127.0.0.1:55417` |
| Redis | Docker `redis:7-alpine` (7.4.11), `127.0.0.1:56379` |
| Compose file | `docker-compose.merge-dev.yml` + `.env.merge-dev.example` (fake passwords). `docker compose config` showed `host_ip: 127.0.0.1` for all 3 published ports |
| Many Python | 3.11.18 (matches Many's `backend/Dockerfile` and CI); pytest 9.2.0 |
| SaaS Python | 3.12.15; pytest 9.1.1, ruff 0.17.0, mypy 2.4.0 |
| Node / npm | v24.22.3 / 11.19.1 (SaaS pin `>=24 <25` satisfied) |
| uv | 0.13.9 |
| Download checks | Node tarball `node-v24.22.3-linux-x64.tar.xz`: `sha256sum -c` against the official `SHASUMS256.txt` printed **OK**. uv 0.13.9: SHA-256 of the release tarball equals the published `.sha256` (printed, **OK**) |
| Dependencies | Many: `requirements.txt` is unpinned and identical in both trees; resolved once in the original venv (68 packages), the frozen list was installed in the new venv (freeze md5 identical: `4c30f8ed...`). SaaS: `requirements-dev.lock` (identical in both trees). Web/dashboard: `npm ci` from the lock files (exit 0 in all four trees). Fresh venv / `node_modules` per tree |
| Trees | `orig/many` = `da3ed28` (clean clone of the read-only original), `orig/saas` = `26d6b66` (same), `new` = `32da29e` cloned from GitHub. All under `~/phase1b/` on the WSL filesystem. Push URL of `new` was disabled while testing |
| Credentials | Every test ran under `env -i` with fake values only (`fake-*`, a random throwaway Fernet key generated per run, empty `SENTRY_DSN`). No real OPENAI/Meta/other credential was present in the run environments; the one sensitive-looking name on the Windows side (`CLAUDE_CODE_EXECPATH`) is a harness path, not a credential. No `.env` file was opened |
| External hosts | `HTTP(S)_PROXY`/`ALL_PROXY` pointed to a dead local port (`127.0.0.1:9`, `NO_PROXY=127.0.0.1,localhost`) so any outbound HTTP would fail visibly. Search of the final logs for proxy/DNS/connection errors and `api.openai` / `graph.facebook`: **0 hits in all four final pytest logs**. This is a best-effort tripwire, not a network firewall (raw sockets would not be caught). No external-host finding |

Before every run the runner printed `APP_ENV=test`, the DB host (or socket) and the DB name; `TEST_DATABASE_URL` was set explicitly.

## Results: original vs new

| Suite | Command (cwd) | Original `da3ed28` / `26d6b66` | New `32da29e` | Same? |
|---|---|---|---|---|
| Many backend pytest | `python -m pytest tests -q` (`backend/`) | **1007 passed**, 0 failed, 0 errors, 0 skipped (200 s) | **1007 passed**, 0 failed, 0 errors, 0 skipped (206 s) | yes; equals recorded baseline 1007/0/0 |
| Many scripts unittest | `python -m unittest discover -s scripts -p 'test_*.py' -v` (repo root) | 29 tests OK | 29 tests OK | yes; equals baseline 29 |
| Many `scripts/check_contract_copies.py` | from repo root | exit 0, "contract copies OK (3 LF-normalised SHA256 hashes)" | exit 0, same message | yes |
| Many dashboard typecheck | `npx tsc --noEmit` (`dashboard/`) | exit 0 | exit 0 | yes |
| Many dashboard lint | `npm run lint` (`dashboard/`) | exit 0, 1 warning (`accounts/page.tsx:510` missing `toast` dep) | exit 0, same 1 warning | yes; warning is the one Many's evidence README already lists |
| SaaS API pytest | `python -m pytest -q` (`apps/api/`) | 1215 passed, **1 failed**, 0 errors, 0 skipped (52 min) | 1215 passed, **1 failed**, 0 errors, 0 skipped (52 min) | yes (same single failure, see below) |
| SaaS API: that 1 test, re-run with its required env | `pytest tests/test_r19_index_migration.py` | 1 passed | 1 passed | yes |
| SaaS ruff | `ruff check .` and `ruff format --check .` | both exit 0 (304 files formatted) | both exit 0 (304 files) | yes |
| SaaS mypy | `mypy` | Success, 289 source files | Success, 289 source files | yes |
| SaaS `scripts/check_contract_copies.py` | `python scripts/check_contract_copies.py` from the SaaS root (`modules/saas/` in the new tree) | exit 0 "contract copies OK" | exit 0 "contract copies OK" | yes; no path broken by the move |
| SaaS scripts unittest | `python -m unittest discover -s scripts -p 'test_*.py'` (SaaS root) | 23 OK | 23 OK | yes |
| SaaS web unit | `node --test tests/insights.unit.mjs` (`apps/web/`) | 8 pass / 0 fail / 0 skipped | 8 / 0 / 0 | yes |
| SaaS web lint | `npm run lint` (SaaS root) | exit 0 | exit 0 | yes |
| SaaS web typecheck | `npm run typecheck` (SaaS root) | exit 0 | exit 0 | yes |
| SaaS web `format:check` | `npm run format:check` (SaaS root) | **exit 2**: 4 files not formatted | **exit 2**: the same 4 files (diff of the warning lists: identical) | yes (failure exists in the original; recorded, not fixed) |

### The one SaaS failure (identical in both trees)

`tests/test_r19_index_migration.py::test_health_lookup_index_roundtrip_and_head_drift` failed with `KeyError: 'PGHOST'`
in the full run. That test requires `ENVIRONMENT=test` and `PGHOST` pointing at a local Unix-socket directory
`/var/tmp/saas-*/<dir>` with a `.s.PGSQL.<port>` socket (it was written for a socket-only Postgres). My runner did not provide
it, so this is an environment gap of this verification, not a regression. Re-running only that test with a socket bridge
(see below), `ENVIRONMENT=test`, `PGHOST=/var/tmp/saas-phase1b/sock`, `PGPORT=55417`, it passed in both trees. The **full**
SaaS suite was not re-run with the extra variables (52 minutes per tree); the full-run figure stays 1215 passed / 1 failed.

## Deviations and things to know

1. **Many needed three attempts to match the baseline; all attempts are recorded.**
   - Run 1 (62 failed, 870 passed, 75 errors, original only): my runner lacked `TOKEN_ENCRYPTION_KEY` (129 `RuntimeError: TOKEN_ENCRYPTION_KEY is not configured`).
   - Run 2 (both trees: 993 passed, 14 failed): remaining failures were environment coupling in the tests, identical failing ids in both trees: tests that assert a Unix-socket Postgres host under `/var/tmp/` or `/tmp/` (migration tests, processed-event tests, `scripts/test_canary_preflight.py`, which also errored in the scripts suite: "Only disposable local-socket many_test is permitted"), and webhook signature tests (403) because my `META_WEBHOOK_SECRET` differed from `META_APP_SECRET`; the app signs with `META_WEBHOOK_SECRET or META_APP_SECRET`.
   - Run 3 (final, both trees): `META_WEBHOOK_SECRET` and `FACEBOOK_APP_SECRET` empty; Postgres reached through a socket (below). Result 1007/0/0 and 29 OK in both trees.
   No test or code was edited to get there; only the environment changed.
2. **Unix-socket bridge.** Because those tests demand a local socket, I ran a ~20-line stdlib Python forwarder
   (`unix socket -> 127.0.0.1:<port>`) in WSL in front of the same Docker Postgres 15 (Many, socket `/var/tmp/many-r1-phase1b`) and
   Postgres 17 (SaaS single test, `/var/tmp/saas-phase1b/sock`). It is the same real database server, not a substitute DB.
3. **Many DB name.** Tests assert the database name `many_test_r1`, so the original and the new tree both used a database
   called `many_test_r1`, run one after the other, dropped and re-created before each run (not two names at once). The SaaS used
   `saas_orig_test` / `saas_new_test`.
4. **SaaS pytest ran for both trees at the same time** (separate databases, same server) to save time; timings are therefore not comparable with a quiet machine. I also killed the first original-tree run by mistake (operator error, a `kill` on the wrong parent process) and restarted it; the restarted run is the one reported. The killed log is kept as `saas-orig-pytest.killed-by-operator-error.log` in the WSL results folder.
5. **Test side effects in the clones (both trees).** Running the tools modified tracked files inside the scratch clones: `dashboard/tsconfig.tsbuildinfo` (tsc) and `modules/saas/implementation/PHASE-03/EVAL-REPORT.md` (a SaaS test rewrites it). Nothing from the clones was committed; worth knowing for CI (a SaaS test writes into a tracked file).
6. **Many `scripts` contract unit test invoked as a module** (`python -m unittest scripts.test_check_contract_copies`) fails because `scripts/` is not a package: my invocation, not a repo problem. The same test file runs inside the 29-test discover run, which passes.
7. **Many requirements are unpinned**: results depend on the versions resolved on 2026-11-23 (list frozen in the scratch venv, not committed).

## NOT RUN (with reason)

| Item | Reason |
|---|---|
| SaaS web Playwright e2e (`npm test`) | Needs Playwright browsers and the API/worker booted; out of Phase 1b scope in the brief (unit/lint/typecheck only) |
| `npm audit --omit=dev` (SaaS CI step) | Needs a registry audit call; not part of the brief |
| Full SaaS pytest re-run with `PGHOST`/`ENVIRONMENT` set | 52 min per tree; the single affected test was re-run in both trees instead |
| Many dashboard / SaaS web build (`next build`) | Not requested |
| CI service containers (GitHub Actions) | Not needed: Docker was available locally. No workflow was added |

## Commands (exact, abbreviated paths; scripts kept in the session scratchpad, not committed)

```
# tools
curl nodejs.org/dist/latest-v24.x/SHASUMS256.txt ; sha256sum -c   # node-v24.22.3 OK
uv python install 3.12 ; uv python install 3.11
# services
docker compose -f docker-compose.merge-dev.yml --env-file .env.merge-dev.example config   # all ports host_ip 127.0.0.1
docker compose -f docker-compose.merge-dev.yml --env-file .env.merge-dev.example up -d
# venvs / node
uv venv --python 3.11 venvs/many-{orig,new}; uv pip install -r requirements.txt (orig) / frozen list (new)
uv venv --python 3.12 venvs/saas-{orig,new}; uv pip install -r requirements-dev.lock
npm ci  (orig/many/dashboard, new/dashboard, orig/saas, new/modules/saas)
# Many (env -i, APP_ENV=test, TEST_DATABASE_URL=postgresql+psycopg://...@/many_test_r1?host=/var/tmp/many-r1-phase1b&port=55415)
cd backend && python -m pytest tests -q -p no:cacheprovider -rfEs --junitxml=...
python -m unittest discover -s scripts -p 'test_*.py' -v
cd dashboard && npx tsc --noEmit ; npm run lint
python scripts/check_contract_copies.py
# SaaS (env -i, APP_ENV=test, TEST_DATABASE_URL=postgresql://...@127.0.0.1:55417/saas_{orig,new}_test)
cd apps/api && python -m pytest -q -p no:cacheprovider -rfEs ; ruff check . ; ruff format --check . ; mypy
python scripts/check_contract_copies.py ; python -m unittest discover -s scripts -p 'test_*.py'
npm run format:check ; npm run lint ; npm run typecheck ; node --test apps/web/tests/insights.unit.mjs
```

## Cleanup

Only objects created by this session were removed (names are listed in `docs/MERGE-PROGRESS.md`, "Last session"). Nothing else in Docker Desktop was touched.
