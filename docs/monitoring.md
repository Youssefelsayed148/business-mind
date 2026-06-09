# Monitoring

## Sentry

Set `SENTRY_DSN` in `.env.production` to enable backend exception capture.

```text
SENTRY_DSN=https://examplePublicKey@o0.ingest.sentry.io/0
```

The backend tags events with `APP_ENV`, so production errors are separated from local development.

## Uptime Checks

Use UptimeRobot, BetterStack, or another external monitor for:

```text
https://automation.yourdomain.com/health
https://automation.yourdomain.com/webhooks/health
```

Recommended check interval: 1 minute for `/health`, 5 minutes for `/webhooks/health`.

## Docker Logs

Inspect logs:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f nginx
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f backend
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f worker
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f beat
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f postgres
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f redis
```

Check service state:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

## Critical Alerts

Alert on these conditions:

- Backend down: `/health` returns non-200 or `database`/`redis` is `error`.
- Worker down: `worker` container is not running or webhook processing queue grows.
- Redis down: `/health` reports `redis: error`.
- Postgres down: `/health` reports `database: error`.
- SSL expiring: certificate has fewer than 14 days remaining.
- Token expiring: connected Instagram account token reaches `Expiring Soon`.
- High failed message rate: failed messages exceed expected baseline.
- No webhook events: `/webhooks/health` stays `unknown` or `last_event_received_at` is stale during expected traffic.

## Useful Commands

Disk usage:

```bash
df -h
docker system df
```

Container resource use:

```bash
docker stats
```

Recent failed messages can be inspected in the dashboard `Messages` page and retried if they are retryable.
