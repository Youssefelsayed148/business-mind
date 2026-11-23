# Group 2: A5/A6/A7 ? 2026-10-28

Worktree: `.closeout-worktrees/a5-a7`; branch `closeout/a5-a7`; base `13c7873`.
No commit, push, merge, deployment, live send or authenticated API call.

## Files changed

- `backend/app/api/routes_webhooks.py`: verify token with `secrets.compare_digest` on UTF-8 bytes; Unicode rejects cleanly.
- `backend/app/services/rate_limit_service.py`: use ASGI `request.client`, never raw forwarding headers. Uvicorn owns peer validation.
- `backend/app/core/config.py`: clarify legacy proxy-header flag.
- `docker-compose.traefik.yml`: remove wildcard proxy trust, interpolate explicit `FORWARDED_ALLOW_IPS` with fail-closed loopback default. Operators must supply actual ingress peer IP/CIDRs through Compose interpolation, not merely container env_file.
- `scripts/preflight_prod.py`: require explicit proxy IP/CIDRs, reject wildcard/global routes/empty peer list.
- `scripts/canary_preflight.py`: selected WhatsApp delegation must be enabled with canonical connection UUID, public HTTPS URL syntax and nonempty stored secret. Query returns only secret-presence Boolean, never ciphertext. No DNS/HTTP calls. New required readiness input `--beat-process-count 1` means an operator independently observed exactly one deployed beat; source schedule check is separate.
- Tests: `backend/tests/test_meta_webhooks.py`, `test_preflight_prod.py`, new `test_forwarded_ip_trust.py`, `scripts/test_canary_preflight.py`.
- Evidence: this directory. Source-only snapshot ZIP removed after validation; scripts/logs/XML retained. `python docs/saas-delegation/a5-a7-evidence/make_snapshot.py` recreates the input archive (not executed after validation; no test-source changes).

## Tests added

Forwarding header spoofing with legacy flag on/off; trusted/untrusted Uvicorn proxy peer; spoofed leftmost IP through trusted proxy chain; Unicode verification token; constant-time byte compare call; unsafe proxy allowlists; HTTPS/private/credential/query URL checks; disabled/missing-secret delegation rejection; independent one-beat input and full CLI rejection when missing/zero/two. Canary synthetic fixture schema expanded only with required delegation fields. Named test DBs allowed by strict `many_test` / `many_test_<suffix>` guard for parallel workers.

## Exact commands and outcomes

From worker worktree:

1. `git worktree add -b closeout/a5-a7 .closeout-worktrees/a5-a7 HEAD` from parent root: default sandbox denied Git ref lock; identical escalated command succeeded, base `13c7873`.
2. `python -m compileall -q scripts/canary_preflight.py scripts/test_canary_preflight.py scripts/preflight_prod.py backend/tests/test_forwarded_ip_trust.py`: exit 0. `git diff --check`: exit 0, only CRLF conversion advisories.
3. `wsl -d Ubuntu -u root -- bash '/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/.closeout-worktrees/a5-a7/docs/saas-delegation/a5-a7-evidence/run-tests.sh'`: exit 0. Nested pytest: `APP_ENV=test TEST_DATABASE_URL="$TEST_DATABASE_URL" pytest tests/test_meta_webhooks.py tests/test_preflight_prod.py tests/test_production_hardening.py tests/test_rate_limit_isolation.py tests/test_forwarded_ip_trust.py -q --junitxml="$evidence/tests.xml"`: **25 passed**, 0 failures/errors/skips, 1 dependency deprecation warning, 1.43 s. XML independently counted. Nested canary unittest: **19 passed**, 0.589 s.
4. URL check was then aligned with runtime contract to permit HTTPS path prefixes/custom ports, and one missing-count CLI regression was added. Only canary tests rerun: `wsl -d Ubuntu -u root -- bash '/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/.closeout-worktrees/a5-a7/docs/saas-delegation/a5-a7-evidence/rerun-canary.sh'`: exit 0, nested `APP_ENV=test TEST_DATABASE_URL="$TEST_DATABASE_URL" python -m unittest discover -s scripts -p test_canary_preflight.py -v`: **20 passed**, 0.666 s. Current `canary.log` is final run; first run count recorded from tool output. Source ZIP refresh emitted duplicate-member warnings; extraction used the latest entries and final source was tested. No full suite run.

Environment: own fresh disposable PostgreSQL 18 cluster `/var/tmp/many-a5-a7-20261028/pg`, socket `/var/tmp/many-a5-a7-20261028/socket`, port 55437, `listen_addresses=''`, DB `many_test_a5_a7`. Explicit APP_ENV/test URL each test command, URL identity asserted and host/db printed. DATABASE_URL unreachable sentinel. Cached T0 Python 3.11 venv. No environment files in source snapshot. Redis port 56379 in private loopback-only `unshare --net`, namespace unique per invocation; FLUSHALL applies only there. Cluster stopped and Redis terminated after both runs.

## A5: public documentation lookup ? UNVERIFIED

No Graph version bump made. `web.open` on official URLs returned:

- https://developers.facebook.com/docs/graph-api/changelog/versions/ ? HTTP 429.
- https://developers.facebook.com/docs/instagram-platform/changelog/ ? HTTP 429.
- https://developers.facebook.com/docs/graph-api/changelog/ ? HTTP 429.
- https://developers.facebook.com/docs/graph-api/changelog/version26.0/ and same without trailing slash ? inaccessible via tool.
- https://developers.facebook.com/blog/post/2026/07/29/introducing-graph-api-v26-and-marketing-api-v26/ ? inaccessible via tool.
- Official-domain `web.search_query` for Graph v26 changelog and v21 availability ? empty results.

Initial unrestricted search surfaced third-party version tables, but those are not accepted as technical evidence and no expiry/current-version claim is based on them. R8/A5 stays open pending accessible official changelog and endpoint compatibility review. No authenticated Meta request occurred.

## Open questions and risks

- D5 remains OPEN per owner instruction; untouched.
- Lead must update `CANARY.md` commands for `--beat-process-count` and expanded synthetic schema/read-only field descriptions (outside worker ownership).
- Runtime ingress addresses must be supplied correctly; loopback default can combine all clients under ingress IP until configured, safely refusing spoofing. `FORWARDED_ALLOW_IPS` is a Compose interpolation variable: deployment must pass the approved env file via Compose `--env-file` or shell. No real deployment configuration inspected.
- Preflight proves secret presence, not decryption/key correctness; URL DNS/public resolution and actual beat process observation remain deployment checks. No schema or nondelegated dispatch changes.
- Full suites, live canary, nginx/Traefik runtime and hosted CI: UNVERIFIED, intentionally left to lead/final authorized runs.
