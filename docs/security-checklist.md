# Security Checklist

Before production launch:

- No secrets committed to Git.
- `.env.production` exists only on the server and is not committed.
- `JWT_SECRET`, `APP_SECRET_KEY`, `POSTGRES_PASSWORD`, and `META_WEBHOOK_VERIFY_TOKEN` are strong random values.
- `TOKEN_ENCRYPTION_KEY` is a valid Fernet key and Meta access tokens are encrypted at rest.
- No plaintext token regression: tests covering encrypted token storage still pass.
- Postgres is not publicly exposed; it has no host port in `docker-compose.prod.yml`.
- Redis is not publicly exposed; it has no host port in `docker-compose.prod.yml`.
- Webhook signature validation is enabled and unsigned webhook POSTs return 403.
- HTTPS is enabled for the production domain.
- HTTP redirects to HTTPS.
- Nginx rate limits `/webhooks/meta`.
- `ALLOWED_ORIGINS` is restricted to the production domain.
- FastAPI docs are disabled in production when `DISABLE_DOCS=true`.
- Admin password is strong and stored in a password manager.
- SSH password login is disabled on the VPS.
- UFW allows only 22, 80, and 443.
- Backups are generated on schedule.
- Backups are copied off-server.
- Restore has been tested on a non-production environment.
- Meta app permissions are minimal for the current automation scope.
- Meta webhook verify token is not reused across unrelated systems.
- Sentry or equivalent exception monitoring is configured.
- Uptime checks cover `/health` and `/webhooks/health`.
