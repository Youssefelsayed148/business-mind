# Rate Limiting

ManyOsirisChat uses Redis-backed API rate limits for sensitive and high-traffic backend routes.

## Configuration

Set `RATE_LIMIT_ENABLED=false` to disable limits for local stress testing.

Default limits:

- `POST /auth/login`: 5 attempts/minute per IP + email, 20 attempts/15 minutes per IP.
- `POST /webhooks/meta`: `WEBHOOK_IP_LIMIT` per `WEBHOOK_IP_WINDOW_SECONDS`, default 300/minute.
- Campaign mutations: `MUTATION_USER_LIMIT` per authenticated user, default 60/minute.
- Account mutations: `ACCOUNT_MUTATION_USER_LIMIT` per authenticated user, default 30/minute.

Proxy headers are ignored unless `TRUST_PROXY_HEADERS=true`.

## Manual Checks

1. Submit 6 wrong login attempts for the same email within 1 minute. The 6th request should return `429` with `Too many login attempts. Please try again later.`.
2. Wait for `LOGIN_EMAIL_IP_WINDOW_SECONDS`, then confirm a correct login works.
3. Run `scripts/send_mock_instagram_webhook.py`; normal usage should stay below the webhook limit.
4. Rapidly trigger campaign create/update/status actions as one user; requests eventually return `429`.
5. Confirm viewer/operator unauthorized mutations return `403` until a real rate limit is exceeded.
6. Set `RATE_LIMIT_ENABLED=false`, restart the backend, and confirm limits are bypassed.
7. Check `/logs` for `login_rate_limited`; metadata should include IP, path, and window, without passwords or tokens.
