# Deploy outline (Phase 2b): OUTLINE ONLY

Nothing in this document has been executed or approved. There is no deploy script. Every step that touches a live system needs the owner's explicit approval first. `docker-compose.unified.prod.yml` is written, never deployed.

## Open decisions before any deployment

**Owner decision 2026-11-24:** the production HTTPS requirement stays (not relaxed). Decisions 1 and 2 below (edge TLS; internal TLS with a private CA) are Phase 6 items and remain OPEN. Until they are done the prod overlay is written but not deployable.

1. **TLS at the edge.** `nginx/unified.conf` is plain HTTP. Choose: TLS terminated by a load balancer in front, or a TLS server block in nginx with certificates.
2. **Internal TLS.** In production the allowlist policy still requires HTTPS for the listed service names, so the internal URLs stored on the channel rows (`http://saas-api:8000`, `http://many-api:8000`) are rejected. Production needs `https://` internal URLs (internal CA or service certificates) before delegation can be enabled. Without it, delegation stays off.
3. **Domains and cookies.** Real `MANY_HOST`, `SAAS_WEB_HOST`, `SAAS_API_HOST`. SaaS session cookies are host-only, `HttpOnly`, `SameSite=Lax`, `Secure` when `COOKIE_SECURE=true` (set by the prod overlay); the SaaS web talks to its API same-origin through the Next `/api` rewrite, so the dashboard uses the SaaS web host only.
4. **Secrets.** Source of the real values (secret manager or host-only env file). Never in git. Rotation owners for the Meta token/webhook secret/verify token noted in `docs/MERGE-PROGRESS.md`.
5. **Which Instagram path stays frozen** and who approves any change to it (project rule).

## Steps (each needs approval)

1. Freeze and tag-free checkpoint: confirm the merged commit, run the local gates (full Many and SaaS suites, policy and contract copy checks), record results. GitHub Actions is paused for billing, so all gates are local.
2. Back up both databases (Many pg15, SaaS pg17) and verify a restore on a throwaway host (`docs/backup-and-restore.md`).
3. Prepare the host: Docker, firewall (only the edge port(s) open), DNS for the three hosts, secrets in place.
4. Build images (`docker compose ... build`); constraints file `backend/constraints.txt` for reproducible Many installs.
5. Run both Alembic chains separately (`many-migrate`, `saas-migrate`); heads must match the repo (Many `0030_meta_account_erasure`, SaaS `0031_contact_erasure` at Phase 2b start).
6. Start databases, redis, APIs, workers, dashboards, then nginx; check every healthcheck.
7. Edge verification from outside: signed routes (`/api/saas/*`, `/saas/*`, `/api/channels/*`) return the edge 403; JWT admin routes return the app's 401/403 unauthenticated.
8. Delegation stays OFF per channel until decision 2 is resolved and the owner approves turning it on, one channel at a time.
9. Rollback: stop the new stack, restore the databases from the step 2 backups, return DNS to the previous target.

## Out of scope here

Identity, single dashboard shell, unified data (Phases 3 to 5); Many DNS transport pinning and `host:port` allowlist entries (Phase 6 candidates).
