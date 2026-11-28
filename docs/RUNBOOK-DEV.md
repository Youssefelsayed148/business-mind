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
| TLS | yes (443, certificates) | dev: no. Prod: yes, chosen by mounting `nginx/edge/https` and `nginx/upstream/tls` (Phase 6A, `docs/staging/6A-edge-and-internal-tls.md`) |
| Many `/api/saas/*` and `/saas/*` (HMAC-signed service-to-service) | public, with the `saas_signed` rate limit (lines 64 and 71) | **denied, 403**, `^~` prefix locations; SaaS reaches them as `http://many-api:8000` |
| SaaS `/api/channels/*` (signed events endpoint) | not proxied | **denied, 403** on both SaaS hosts (the web host rewrites `/api/*` to saas-api) |
| All other Many routes (`/webhooks/meta`, `/api/`, `/auth/`, `/instagram/`, ..., `/`) | as is | copied unchanged (upstream names differ) |
| `/auth/sso/exchange` (Phase 3, closed in Phase 4F) | not present | **denied, 403**, exact locations and case-insensitive twins, Many host only; SaaS reaches it as `http://many-api:8000/auth/sso/exchange` |
| SaaS web and API | not present | served by hostname (no Next basePath, so no SaaS code change) |

The deny response is `403` with body `denied at the edge` and header `X-Edge-Deny: 1`, so it cannot be confused with an application answer. `e2e/phase2/check_nginx.py` proves the deny rules for spelling variants (double slash, percent-encoding, dot segments) and that they do not shadow the JWT/session admin routes; results are in `docs/PHASE-2-RESULTS.md`.

## Identity and SSO (Phase 3): every flag is OFF by default

Design: `docs/IDENTITY-DESIGN.md`. Nothing below runs unless you turn a flag on in `.env.unified`. With all flags off both apps behave exactly as before Phase 3 (new routes answer 404 like unknown routes, no new column is read).

### Flag matrix

| Flag | App | Default | Effect when off |
|---|---|---|---|
| `IDENTITY_V2_ENABLED` | SaaS | false | roles, locations, agencies, team routes, reset, MFA routes, session policy and login hardening are inactive; `memberships.role` stays authoritative |
| `SSO_ISSUER_ENABLED` | SaaS | false | `/api/v1/sso/*` answers 404, nothing is minted |
| `SSO_ASSERTION_ENABLED` | Many | false | `/auth/sso/exchange` answers 404, `sso_access` tokens are rejected |
| `MFA_ENFORCE_STAFF`, `MFA_ENFORCE_ADMINS` | SaaS | false | MFA is optional (enforcement is applied when an assertion is minted; admins get a 14-day grace from the day they joined) |
| `SSO_REQUIRE_MFA_FOR_ADMIN` | Many | false | the exchange does not check the `mfa` claim |

Other settings (names only, values in `.env.unified`): SaaS `SSO_SIGNING_KID`, `SSO_SIGNING_KEY_PEM`, `SSO_RETURN_ALLOWLIST` (JSON list of exact callback URLs), `MFA_SECRET_ENCRYPTION_KEYS`, `PUBLIC_BASE_URL`, `MAILER_BACKEND` (`console` is the only backend: it sends nothing, the invite screen shows the one-time link); Many `SSO_PUBLIC_KEYS` (JSON `{kid: PEM public key}`), `SSO_ISSUER`, `SSO_AUDIENCE`, `SSO_TOKEN_MINUTES`.

### Make dev keys (never commit them; keep them outside the checkout)

```bash
# Ed25519 pair for the SSO assertion (SaaS signs, Many verifies)
openssl genpkey -algorithm ed25519 -out ~/sso-dev-private.pem
openssl pkey -in ~/sso-dev-private.pem -pubout -out ~/sso-dev-public.pem
# One-line forms for .env.unified (PEM with literal \n sequences)
awk 'NF {sub(/\r/, ""); printf "%s\\n", $0}' ~/sso-dev-private.pem   # -> SSO_SIGNING_KEY_PEM=...
awk 'NF {sub(/\r/, ""); printf "%s\\n", $0}' ~/sso-dev-public.pem    # inside SSO_PUBLIC_KEYS={"dev-1":"..."}
# SSO_SIGNING_KID=dev-1   (must be a key id present in Many's SSO_PUBLIC_KEYS)
# Fernet key for MFA secrets
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # -> MFA_SECRET_ENCRYPTION_KEYS
```

SaaS startup refuses an unusable signing key when `SSO_ISSUER_ENABLED=true`; Many refuses an empty or malformed `SSO_PUBLIC_KEYS` when `SSO_ASSERTION_ENABLED=true`. Key rotation, with no downtime: add the new public key to Many's map, switch the SaaS to the new `kid`, remove the old key after two minutes. Emergency revocation: remove the `kid` from Many (all outstanding assertions die within 60 seconds, Many tokens within 10 minutes).

### Edge: the exchange route

`nginx/unified.conf` denies `/auth/sso/exchange` (and `/api/auth/sso/exchange`) on the Many host with the same `403` and `X-Edge-Deny: 1` as the signed routes, in every spelling (exact locations plus case-insensitive twins). Since Phase 4F the SaaS API exchanges server-side over the internal network, so the browser never needs the route. The SaaS hosts do not route that path to Many. `nginx/default.conf` is not edited. Rollback: restore the previous `unified.conf` (the public location with the `sso_exchange` limit). Re-run `scripts/dev-up.sh test` after any change to `unified.conf`.

### Migrating Many users (rehearsal only, never production in Phase 3)

`scripts/identity_migrate.py` links Many users to SaaS users offline. Dry run first; the report (with emails and the hash algorithm of every Many row, never a hash) is written outside the repository:

```bash
MANY_DATABASE_URL=... SAAS_DATABASE_URL=... python scripts/identity_migrate.py report --out ~/identity-report.json
# review it, take a backup of both databases, then:
python scripts/identity_migrate.py apply --report-hash <hash from the report> --confirm-databases <many_db>,<saas_db> --yes
python scripts/identity_migrate.py verify
```

Only argon2id hashes are carried; any other algorithm is reported as "needs set-password link" and gets an unusable password until a link is used. Memberships are not applied by this tool. The organization to workspace mapping is a separate step (next section). Its tests need a disposable Postgres (`APP_ENV=test`, `TEST_DATABASE_URL`).

### Organization to workspace mapping and the Many proxy (Phase 4A)

The owner decides which SaaS organization belongs to which Many workspace and writes a JSON file of
`{"tenant_id": "...", "workspace_id": "..."}` pairs (one organization to one workspace, both ids as UUIDs).
Same environment and safety rules as above (`MANY_DATABASE_URL`, `SAAS_DATABASE_URL`, throwaway databases for tests, a backup before any apply):

```bash
python scripts/identity_migrate.py map-report --mapping pairs.json     # read-only; prints the hash and any conflict
python scripts/identity_migrate.py map-apply --mapping pairs.json --report-hash <hash> --confirm-databases <many_db>,<saas_db> --yes
python scripts/identity_migrate.py verify-mapping                       # both sides point at each other
```

`map-apply` refuses on any conflict (unknown or archived organization, unknown workspace, either side already mapped elsewhere), writes only empty pointers, and a stopped run is finished by running it again.

The proxy (`MANY_PROXY_ENABLED`, off by default) also needs `IDENTITY_V2_ENABLED`, `SSO_ISSUER_ENABLED` and a Many with `SSO_ASSERTION_ENABLED` and the matching `SSO_PUBLIC_KEYS`. `MANY_API_BASE_URL` defaults to `http://many-api:8000`, the one host `CHANNEL_INTERNAL_ALLOWED_HOSTS` allows. With it off, every `/api/v1/many/*` path answers 404 like an unknown route. The browser never receives a Many token or a workspace id; only the paths listed in `modules/saas/apps/api/app/identity/many_routes.py` are forwarded. Turning the flag off is the rollback.

#### The public opt-in call (Phase 4C)

`POST /api/v1/many/public/whatsapp/opt-in/{token}` is the only proxy call without a login. It is
off with the proxy flag, accepts only `{"phone": "+<6 to 20 digits>"}`, is limited here (10 per
address and 100 per link per hour) and is forwarded with the customer's address in
`X-Forwarded-For`. **Prerequisite before turning it on:** Many records the address it sees as
consent evidence and applies its own per-address limit (`WHATSAPP_PUBLIC_OPT_IN_IP_LIMIT`, 10 per
hour). `docker-compose.unified.yml` starts Many's uvicorn without `--proxy-headers`, so Many would
see this API's address for every customer: one shared limit and wrong evidence. Start Many with
`--proxy-headers --forwarded-allow-ips=<the SaaS API's address>` (not `*`) before relying on it, or
keep serving the opt-in page from the old dashboard (the link base is `DASHBOARD_BASE_URL`).
Not tested here (no Docker daemon).

### Rollback ladder

1. Turn the flags off (seconds): Many's own login works as before, SSO tokens are rejected, SaaS roles fall back to the legacy column.
2. Empty `SSO_PUBLIC_KEYS` in Many: every exchange is refused.
3. Downgrade Many `0031_sso_link` and SaaS `0034` to `0032` only after a fresh backup (shadow users are harmless leftovers).
4. Full restore from backup.

## Constraints file

`backend/constraints.txt` is the Many dependency freeze (68 pinned packages, MD5 `4c30f8edc6ffa514c5e3c7e2237be481`, no index URLs or credentials). It is for reproducible installs (`pip install -r requirements.txt -c constraints.txt`); `requirements.txt` and the Many Dockerfile are unchanged.

## Troubleshooting

- `docker info` fails: start Docker Desktop.
- `dev-up.sh up` stops with "Missing .env.unified": create it from the example.
- Compose says a variable is missing: `MANY_DB_PASSWORD` / `SAAS_DB_PASSWORD` must be set in `.env.unified`.
- On Windows Git Bash, paths like `/e2e/...` are rewritten unless `MSYS_NO_PATHCONV=1` (the script sets it).
- Port busy: set `UNIFIED_HTTP_PORT`.
- Do not use `docker compose run driver` without `--no-deps` (it re-runs the one-shot services and regenerates secrets); `dev-up.sh test` already does it right.
