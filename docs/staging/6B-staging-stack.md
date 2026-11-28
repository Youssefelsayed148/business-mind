# Phase 6B: staging stack

Status: **written 2026-11-28; nothing deployed.** Static checks that ran here: `scripts/staging/test_check_outside.py` (6 tests: the outside check passes a correct fake edge and fails on a leaked exchange route, missing HSTS, a missing redirect, an untrusted certificate and a certificate with fewer than 14 days left), `scripts/staging/preflight.sh` run against a placeholder env (fails as it should) and against a filled one with a real generated PKI (passes), `bash -n` on every script, `docker compose config` for the prod overlay. **Not run:** build, start, migrate, any container, certbot, DNS, firewall. D6 approved as recommended: one small VPS, the same Postgres 15 and 17 as production, separate from live. You choose the provider and size.

## What staging is
The production overlay (`docker-compose.unified.prod.yml`) on its own server, own databases, own secrets, a Meta **test** number, no customer data. All identity and data flags stay off until 6G is closed. A staging secret is never a live one: new `META_WEBHOOK_VERIFY_TOKEN`, a test Meta app secret, an OpenAI key with a spend limit.

## Files
| File | Use |
|---|---|
| `.env.staging.example` | Placeholders. Copy to `.env.unified` on the host, `chmod 600` |
| `scripts/staging/preflight.sh` | Read-only checks: env file mode and placeholders, clean checkout, compose config, PKI, edge certificate, flags |
| `scripts/staging/deploy.sh` | preflight, backup (not on `--first-run`), build, start, wait for nginx healthy, outside checks |
| `scripts/staging/check_outside.py` | From another machine: HTTP redirects, certificate chain and days left, HSTS, every edge deny over HTTPS, health |
| `scripts/staging/rollback.sh` | Stop the stack; restore is the manual step in `docs/staging/6C-backup-restore-drill.md` |

## Host checklist (owner)
1. **Server**: Ubuntu LTS, 2 vCPU and 4 GB RAM as a start (see 6F for the real number), 40 GB disk. Docker Engine and the compose plugin (`docs/deployment-vps.md` sections 1 and 2).
2. **Firewall**: UFW allows 22, 80, 443 only (`security-checklist.md`); SSH keys only, password login off; no database or Redis port published (the overlay publishes nginx only).
3. **DNS**: three A records (many, app, api staging names) to the server. Lower the TTL before the first test.
4. **Checkout**: clone the repository at the commit to test; the preflight refuses a dirty tree.
5. **Secrets**: `.env.unified` from `.env.staging.example`, filled on the host only. Generate keys per `docs/RUNBOOK-DEV.md`. Never paste a value into chat or git.
6. **PKI and certificate**: `docs/staging/6A-edge-and-internal-tls.md` steps 1 to 3.
7. **Preflight**: `scripts/staging/preflight.sh` must print `PREFLIGHT PASSED`.
8. **First deploy**: `scripts/staging/deploy.sh --backup-dir /var/backups/business-mind --first-run`. Later deploys drop `--first-run` so a backup is taken first (needs `scripts/ops/backup_all.sh` from 6C).
9. **Migration heads** (UNVERIFIED commands, adjust if the container layout differs): Many `0031_sso_link`, SaaS `0038_grant_location_scope`. `docker compose -f docker-compose.unified.yml -f docker-compose.unified.prod.yml --env-file .env.unified run --rm --no-deps many-migrate alembic current` and the same with `saas-migrate`. Record both outputs.
10. **Outside checks** from your own machine (not the server): `python3 scripts/staging/check_outside.py --many <host> --saas-web <host> --saas-api <host>`; every line must be PASS.
11. **Meta test number**: in the Meta test app set the webhook callback to `https://<MANY_HOST>/webhooks/meta` with the staging verify token (verification call in `docs/deployment-vps.md` section 7). Never point a live app at staging.
12. **Delegation stays off** per channel until 6E says which case to run; internal URLs stored in channel rows are `https://`.

## Rollback
`scripts/staging/rollback.sh` stops the stack and keeps the volumes. To return to the state before a deploy, restore both databases from the `pre-deploy-*` backup folder (6C). Staging has no live traffic, so no DNS or webhook rollback is needed beyond removing the test webhook in the Meta test app.

## Done when (6B)
Preflight passes, deploy finishes, both Alembic heads recorded, `check_outside.py` is all PASS from outside, and the staging run of `docs/staging/6A` open items is written down. A failure is pasted back to me with the last 40 lines of `docker compose ... logs <service>`.

| Item | Result |
|---|---|
| Preflight | |
| Deploy output (last lines) | |
| Many head / SaaS head | |
| `check_outside.py` summary | |
| Anything unexpected | |
