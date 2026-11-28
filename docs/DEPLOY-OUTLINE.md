# Deploy outline (Phase 2b): OUTLINE ONLY

Nothing in this document has been executed or approved. There is no deploy script. Every step that touches a live system needs the owner's explicit approval first. `docker-compose.unified.prod.yml` is written, never deployed.

## Open decisions before any deployment

**Owner decision 2026-11-24:** the production HTTPS requirement stays (not relaxed). **2026-11-28 (Phase 6A):** decisions 1 and 2 below are now written (nginx TLS block with certbot; private CA, `scripts/tls/`, prod overlay) and checked statically only; see `docs/staging/6A-edge-and-internal-tls.md`. They are proven only when the staging stack (6B) runs them.

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
5. Run both Alembic chains separately (`many-migrate`, `saas-migrate`); heads must match the repo (Phase 3: Many `0031_sso_link`, SaaS `0034_roles_backfill`; they were `0030_meta_account_erasure` and `0031_contact_erasure` at Phase 2b start).
6. Start databases, redis, APIs, workers, dashboards, then nginx; check every healthcheck.
7. Edge verification from outside: signed routes (`/api/saas/*`, `/saas/*`, `/api/channels/*`) return the edge 403; JWT admin routes return the app's 401/403 unauthenticated.
8. Delegation stays OFF per channel until decision 2 is resolved and the owner approves turning it on, one channel at a time.
9. Rollback: stop the new stack, restore the databases from the step 2 backups, return DNS to the previous target.

## Identity (Phase 3): decisions and steps before it is switched on

Design: `docs/IDENTITY-DESIGN.md`. Outline only; nothing here is approved or executed.

**Open prerequisites**

- **Email provider (D4).** Only the console mailer exists, so invitations and password-reset links are not delivered by email. Without a provider the inviter must hand over the one-time link, and self-service reset is not usable by real people. Pick a provider before enabling `IDENTITY_V2_ENABLED` for customers.
- **First Owner per organization (D10).** The role backfill maps legacy admins to Admin, not Owner, so no organization has an Owner after the migration. Only platform staff can assign the first Owner (team role change); decide who, per organization, before cutover.
- **TLS.** The assertion travels in a URL fragment and the session cookie is `Secure` in production; both need TLS at the edge (decision 1 above).

**Key custody**

- The SaaS holds the only private key (`SSO_SIGNING_KEY_PEM`); Many holds public keys only (`SSO_PUBLIC_KEYS`), so a Many compromise cannot forge an identity. Store both in the secret manager or a host-only env file, never in git, never in logs or chat.
- `MFA_SECRET_ENCRYPTION_KEYS` (Fernet, newest first) protects stored TOTP secrets. Losing it locks every enrolled person out of login; back it up with the same care as the channel-secret keys, and rotate by prepending a new key.
- Rotation and emergency revocation: `docs/RUNBOOK-DEV.md` (identity section).

**Order of switching on (each step needs approval, one at a time, with a backup before the first)**

1. Run both migration chains (Many `0031_sso_link`, SaaS `0032` to `0034`); everything is still off.
2. Configure keys and `SSO_RETURN_ALLOWLIST` (exact Many dashboard callback URLs); set the Many organization to workspace mapping (`tenants.many_workspace_id` and `workspaces.saas_tenant_id`) for the pilot organization only.
3. Staff first: enroll MFA for every staff account (`/api/v1/auth/mfa/enroll` and `/confirm`), then set `MFA_ENFORCE_STAFF=true`, then `SSO_ISSUER_ENABLED=true` and `SSO_ASSERTION_ENABLED=true`.
4. One pilot organization: assign its Owner, then `IDENTITY_V2_ENABLED=true`. Admins get a 14-day MFA grace when `MFA_ENFORCE_ADMINS=true`.
5. Run the user migration (`scripts/identity_migrate.py`) only against restored copies first (dry run, review, apply, verify), then production with explicit approval.
6. Edge check from outside: `/auth/sso/exchange` and `/api/auth/sso/exchange` return the edge 403 (`X-Edge-Deny: 1`) in every spelling and are not served on the SaaS hosts; the signed routes still return the edge 403; Many's own `/auth/login` still reaches the app.

Rollback: flags off, then empty `SSO_PUBLIC_KEYS`, then the migration downgrades after a backup (`docs/RUNBOOK-DEV.md`).

## Hardening list before production

- **Redis authentication:** set `requirepass` or ACL users on Redis (Celery broker, rate limits and caches for both apps) before production; the dev and e2e stacks run it unauthenticated on a private network only. Update both apps' Redis URLs and the compose healthchecks together.
- **Case-insensitive edge denies:** the signed-route denies include `~*` regex locations (PR #4 review); keep them when adding any new route to the edge, and re-run `e2e/phase2/check_nginx.py` after every `unified.conf` change.

## Out of scope here

The single dashboard shell and unified data (Phases 4 and 5); Many DNS transport pinning and `host:port` allowlist entries (Phase 6 candidates).
