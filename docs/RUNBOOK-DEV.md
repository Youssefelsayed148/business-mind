# RUNBOOK-DEV: unified Many + SaaS stack (local only)

Nothing here deploys anything. Docker Desktop must be running. All commands run from the repo root (Git Bash or WSL).

## Start, test, stop

| Goal | Command |
|---|---|
| Start the dev stack | `cp .env.unified.example .env.unified` (fill it in locally; the file is git-ignored), then `scripts/dev-up.sh up` |
| Throwaway end-to-end run (no egress) | `scripts/dev-up.sh test` (six mock channel cases + nginx edge checks, then it tears itself down; `KEEP=1` leaves it running) |
| Stop | `scripts/dev-up.sh down` |
| Reset (drop volumes, i.e. both databases) | `scripts/dev-up.sh down --volumes` |

`dev-up.sh` uses `docker-compose.unified.yml`; the e2e run adds `docker-compose.unified.e2e.yml` and `e2e/phase2/unified-e2e.env` (throwaway, non-secret values) under a separate compose project (`unified-e2e`), so it never touches the dev stack's volumes.

## Layout

| Piece | What |
|---|---|
| Databases | Two, never merged: `pg15` (Many) and `pg17` pgvector (SaaS), each with its own Alembic chain run by `many-migrate` / `saas-migrate` |
| Dashboards | Both run: Many dashboard and SaaS web (no choice of shell before Phase 4) |
| Edge | `nginx` is the only published service, bound to `127.0.0.1:${UNIFIED_HTTP_PORT:-8080}` |
| Hosts (dev) | `http://localhost:8080` Many; `http://saas.localhost:8080` SaaS web; `http://saas-api.localhost:8080` SaaS API (`*.localhost` resolves to loopback in current browsers; otherwise send a `Host:` header) |
| Internal calls | `many-worker` -> `http://saas-api:8000`, `saas-worker` -> `http://many-api:8000` over the internal network |
| Env scheme | `.env.unified.example` (placeholders only) -> `.env.unified` (git-ignored). Database passwords are required; app secrets are read from the file. Never print or commit the real file |

## CHANNEL_INTERNAL_ALLOWED_HOSTS

Set to `saas-api` for Many and `many-api` for SaaS in the compose files.

- It is **whitespace- and trailing-comma-sensitive**: `saas-api, many-api`, ` saas-api`, `saas-api,` are all invalid. An invalid value **fails startup** (the process exits with an error), it is never silently ignored.
- Entries are single-label service names (no dots, no wildcards, no IP literals, no `localhost`), lowercase.
- **Listed names must resolve to RFC1918/ULA addresses only** (10/8, 172.16/12, 192.168/16, fc00::/7). A public address, or a CGNAT/Tailscale 100.64/10 address, in the answer is rejected, and so is a mixed answer.
- Empty (default) keeps the legacy behavior unchanged. The list is deployment configuration only, never tenant data. Changing it needs a restart of the API and worker processes.
- This is the trusted compose-DNS boundary and **not full SSRF parity** (Many resolves DNS twice; pinning is a Phase 6 candidate; a workspace admin can choose any port/path on a listed host, optional `host:port` entries are a Phase 6 candidate).
- In production the policy still requires HTTPS for these URLs; the e2e run uses development over http, so that rule is covered by unit tests only (`docs/PHASE-2-RESULTS.md`).

## nginx: `nginx/unified.conf` vs `nginx/default.conf` (intentional differences)

`default.conf` is the existing production-style file (TLS, one host) and is never edited. `unified.conf` is an envsubst template (`MANY_HOST`, `SAAS_WEB_HOST`, `SAAS_API_HOST`), plain HTTP, three virtual hosts.

| Topic | default.conf | unified.conf |
|---|---|---|
| TLS | yes (443, certificates) | no (open deployment decision) |
| Many `/api/saas/*` and `/saas/*` (HMAC-signed service-to-service) | public, with the `saas_signed` rate limit (lines 64 and 71) | **denied, 403**, `^~` prefix locations; SaaS reaches them as `http://many-api:8000` |
| SaaS `/api/channels/*` (signed events endpoint) | not proxied | **denied, 403** on both SaaS hosts (the web host rewrites `/api/*` to saas-api) |
| All other Many routes (`/webhooks/meta`, `/api/`, `/auth/`, `/instagram/`, ..., `/`) | as is | copied unchanged (upstream names differ) |
| SaaS web and API | not present | served by hostname (no Next basePath, so no SaaS code change) |

The deny response is `403` with body `denied at the edge` and header `X-Edge-Deny: 1`, so it cannot be confused with an application answer. `e2e/phase2/check_nginx.py` proves the deny rules for spelling variants (double slash, percent-encoding, dot segments) and that they do not shadow the JWT/session admin routes; results are in `docs/PHASE-2-RESULTS.md`.

## Constraints file

`backend/constraints.txt` is the Many dependency freeze (68 pinned packages, MD5 `4c30f8edc6ffa514c5e3c7e2237be481`, no index URLs or credentials). It is for reproducible installs (`pip install -r requirements.txt -c constraints.txt`); `requirements.txt` and the Many Dockerfile are unchanged.

## Troubleshooting

- `docker info` fails: start Docker Desktop.
- `dev-up.sh up` stops with "Missing .env.unified": create it from the example.
- Compose says a variable is missing: `MANY_DB_PASSWORD` / `SAAS_DB_PASSWORD` must be set in `.env.unified`.
- On Windows Git Bash, paths like `/e2e/...` are rewritten unless `MSYS_NO_PATHCONV=1` (the script sets it).
- Port busy: set `UNIFIED_HTTP_PORT`.
- Do not use `docker compose run driver` without `--no-deps` (it re-runs the one-shot services and regenerates secrets); `dev-up.sh test` already does it right.
