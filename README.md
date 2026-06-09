# Instagram Comment-to-DM Automation

Local Dockerized FastAPI backend with PostgreSQL, Redis, Meta webhook validation, authentication, encrypted token storage, Celery workers, campaign management, keyword matching, comment processing, lead creation, and message sending.

## Quick Start

1. Copy environment file:

```bash
cp .env.example .env
```

2. Generate a Fernet encryption key and add it to `.env`:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

3. Start all services:

```bash
docker compose up --build
```

4. Run database migrations:

```bash
docker compose exec backend alembic upgrade head
```

5. Create an admin user:

```bash
docker compose exec backend python -m app.scripts.create_admin --email admin@example.com --password admin123 --name "Admin"
```

6. Verify the service is running:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"status":"ok","service":"Instagram Automation","environment":"development","database":"ok"}
```

The internal marketing dashboard runs at:

```text
http://localhost:3000
```

Docker Compose starts it as the `dashboard` service with `NEXT_PUBLIC_API_URL=http://localhost:8000`.

## Marketing Dashboard MVP

### Login flow

1. Start the stack and run migrations.
2. Create an admin user with `python -m app.scripts.create_admin` or the Docker command above.
3. Open `http://localhost:3000/login`.
4. Log in with the admin email and password. The MVP stores the access token in browser `localStorage`.

### Mock connecting an Instagram account

In development, open `Accounts` and use the `Mock connect account` form. It calls:

```text
POST /meta/connect/mock
```

Use any local test values for `ig_user_id`, `username`, `account_type`, and `access_token`. Connected accounts appear in the accounts table and can be selected when creating campaigns.

### Creating and activating a campaign

1. Open `Campaigns`.
2. Click `New campaign`.
3. Complete the five steps: basics, media, keywords, message, and delivery controls.
4. Click `Save Draft` to create a draft campaign.
5. Click `Activate Campaign` when the account, media ID, message template, and keywords are ready.

The message editor supports both `{username}` and `{{username}}` style variables for:

```text
username, campaign_name, keyword, link, media_url
```

### Running a dry-run simulation

From the campaign form, click `Test Message`, enter a sample comment and username, then run the test. If the campaign has not been saved yet, the dashboard saves a draft first and then calls:

```text
POST /campaigns/{campaign_id}/simulate
```

The modal shows whether a keyword matched and the rendered message body.

### Viewing logs, leads, and messages

- `Overview` shows top-level stats and polls recent automation logs every five seconds.
- `Leads` lists captured leads, supports campaign/status/username filters, and exports CSV.
- `Logs` supports level, campaign ID, event type, and limit filters, with expandable metadata.
- `Messages` lists message status, campaign, lead, retry count, sent time, and errors. Failed messages can be retried from the table.

### Running a dry webhook test

Use the signed webhook flow below in `Webhook Comment Processing` to send a local comment event. Then inspect `Overview`, `Logs`, `Leads`, and `Messages` in the dashboard.

## Authentication

### Login

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin@example.com&password=admin123"
```

Expected response:

```json
{"access_token":"...","token_type":"bearer"}
```

### Get current user

```bash
curl http://localhost:8000/auth/me \
  -H "Authorization: Bearer <access_token>"
```

Expected response:

```json
{"id":"...","email":"admin@example.com","name":"Admin","role":"admin"}
```

### Logout

```bash
curl -X POST http://localhost:8000/auth/logout
```

## Meta Integration

### Mock Account Connection (Development Only)

Use this endpoint to simulate connecting an Instagram account without going through Meta App Review:

```bash
curl -X POST http://localhost:8000/meta/connect/mock \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "ig_user_id": "123456789",
    "username": "testhandle",
    "account_type": "BUSINESS",
    "access_token": "test_access_token_value"
  }'
```

Expected response:

```json
{"status":"connected","account_id":"...","ig_user_id":"123456789"}
```

### List Instagram Accounts

```bash
curl http://localhost:8000/instagram/accounts \
  -H "Authorization: Bearer <access_token>"
```

### Disconnect an Account

```bash
curl -X DELETE http://localhost:8000/instagram/accounts/<account_id> \
  -H "Authorization: Bearer <access_token>"
```

## Campaigns

### Create a Campaign

```bash
curl -X POST http://localhost:8000/campaigns \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "instagram_account_id": "<account_id>",
    "name": "Prompt Giveaway",
    "media_id": "media_123",
    "message_template": "Hey {username}, here is the {keyword} link: {link}",
    "link_url": "https://example.com",
    "keywords": ["prompt", "ai"],
    "match_type": "contains",
    "status": "draft"
  }'
```

### Activate a Campaign

```bash
curl -X POST http://localhost:8000/campaigns/<campaign_id>/activate \
  -H "Authorization: Bearer <access_token>"
```

### Simulate a Campaign

```bash
curl -X POST http://localhost:8000/campaigns/<campaign_id>/simulate \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "comment_text": "I want the prompt",
    "username": "Ahmed"
  }'
```

Expected response:

```json
{
  "matched": true,
  "matched_keyword": "prompt",
  "rendered_message": "Hey Ahmed, here is the prompt link: https://example.com"
}
```

### List Campaigns

```bash
curl http://localhost:8000/campaigns \
  -H "Authorization: Bearer <access_token>"
```

## Webhook Comment Processing

When Meta sends a comment webhook, the backend:
1. Verifies the signature
2. Stores the webhook event
3. Enqueues a Celery worker to process it asynchronously
4. Returns immediately (never blocks the HTTP response)

### Test a Signed Webhook POST Locally

Generate the signature:

```python
import hmac, hashlib, json

body = json.dumps({
    "object": "instagram",
    "entry": [{
        "id": "<ig_user_id>",
        "changes": [{
            "field": "mentions",
            "value": {
                "item": "comment",
                "media_id": "media_123",
                "comment_id": "comment_456",
                "from": {"id": "user_789", "username": "testuser"},
                "message": "I want the prompt"
            }
        }]
    }]
})
sig = "sha256=" + hmac.new(b"local_meta_app_secret", body.encode(), hashlib.sha256).hexdigest()
print(sig)
```

Send the webhook:

```bash
curl -X POST http://localhost:8000/webhooks/meta \
  -H "Content-Type: application/json" \
  -H "X-Hub-Signature-256: <signature>" \
  -d '<payload>'
```

Expected response:

```json
{"status":"received"}
```

### Inspect Messages and Logs

List all messages:

```bash
curl http://localhost:8000/messages \
  -H "Authorization: Bearer <access_token>"
```

Get a single message:

```bash
curl http://localhost:8000/messages/<message_id> \
  -H "Authorization: Bearer <access_token>"
```

Retry a failed message:

```bash
curl -X POST http://localhost:8000/messages/<message_id>/retry \
  -H "Authorization: Bearer <access_token>"
```

## Celery Workers

The `worker` and `beat` services are started automatically by Docker Compose.

To check worker status:

```bash
docker compose logs -f worker
docker compose logs -f beat
```

To run a worker task manually (for testing):

```bash
docker compose exec backend python -c "
from app.workers.tasks import process_webhook_event
process_webhook_event.delay('<webhook_event_id>')
"
```

## Running Tests

Run tests inside the running container:

```bash
docker compose exec backend pytest
```

Or run a one-off test container:

```bash
docker compose run --rm backend pytest
```

## Project Structure

```
backend/
  app/
    main.py                  # FastAPI app entry point
    core/
      config.py              # Pydantic settings
      logging.py             # Structured JSON logging setup
      security.py            # Password hashing & JWT
    db/
      base.py                # SQLAlchemy declarative base
      session.py             # Engine, SessionLocal, get_db dependency
    api/
      routes_health.py       # GET /health
      routes_webhooks.py     # GET/POST /webhooks/meta
      routes_auth.py         # POST /auth/login, GET /auth/me, POST /auth/logout
      routes_meta.py         # Meta OAuth & mock connect
      routes_instagram.py    # Instagram account CRUD
      routes_campaigns.py    # Campaign CRUD, keywords, simulate
      routes_messages.py     # Message list, get, retry
    models/
      user.py                # User model
      workspace.py           # Workspace model
      instagram_account.py   # Instagram account model
      meta_token.py          # Meta OAuth token model
      campaign.py            # Campaign model
      campaign_keyword.py    # Campaign keyword model
      webhook_event.py       # Webhook event model
      comment.py             # Comment model
      lead.py                # Lead model
      message.py             # Message model
      automation_log.py      # Automation log model
      user_cooldown.py       # User cooldown model
      webhook_health.py      # Webhook health model
    schemas/
      auth.py                # Auth request/response schemas
      user.py                # User schemas
      campaign.py            # Campaign request/response schemas
    scripts/
      create_admin.py        # CLI script to create admin user
    integrations/
      meta/
        webhooks.py          # Signature verification & comment parser
        client.py            # Meta Graph API HTTP client
        oauth.py             # Meta OAuth URL builder & token exchange
        accounts.py          # Instagram account metadata fetcher
        errors.py            # Meta API error classification
        messaging.py         # Private reply sender
    services/
      token_service.py       # Encrypted token CRUD
      webhook_event_service.py # Webhook event persistence & dedup
      campaign_service.py    # Campaign CRUD & validation
      campaign_matcher.py    # Keyword matching engine
      template_service.py    # Template rendering service
      cooldown_service.py    # User cooldown tracking
      comment_service.py     # Comment upsert
      lead_service.py        # Lead upsert
      message_service.py     # Message state transitions
      log_service.py         # Automation logging
    utils/
      crypto.py              # Fernet encryption utilities
      normalization.py       # Arabic & English text normalization
      templates.py           # Template variable extraction & rendering
    workers/
      celery_app.py          # Celery app configuration
      tasks.py               # Celery task implementations
      beat_schedule.py       # Celery beat schedule
  tests/
    test_health.py           # Health endpoint tests
    test_meta_webhooks.py    # Webhook route & signature tests
    test_security.py         # Password & JWT tests
    test_auth.py             # Login & /auth/me tests
    test_models.py           # Model constraint tests
    test_crypto.py           # Token encryption tests
    test_meta_integration.py # Mock Meta connect tests
    test_instagram_routes.py # Instagram account route tests
    test_webhook_persistence.py # Webhook storage & dedup tests
    test_celery.py           # Celery import test
    test_normalization.py    # Text normalization tests
    test_templates.py        # Template system tests
    test_campaigns.py        # Campaign service & matcher tests
    test_campaign_routes.py  # Campaign route tests
    test_comment_parser.py   # Comment event parser tests
    test_webhook_processing.py # Webhook processing flow tests
    test_send_private_reply.py # Message sending task tests
    test_meta_errors.py      # Meta error classification tests
    test_message_retry.py    # Message retry endpoint tests
  alembic/
    versions/                # Alembic migrations
  requirements.txt
  Dockerfile
  alembic.ini
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `APP_ENV` | Runtime environment | `development` |
| `APP_NAME` | Service name | `Instagram Automation` |
| `APP_SECRET_KEY` | General app secret | `change_me_local_app_secret` |
| `APP_BASE_URL` | Base URL for OAuth callbacks | `http://localhost:8000` |
| `META_APP_ID` | Meta app ID | `local_meta_app_id` |
| `META_APP_SECRET` | Meta app secret for HMAC verification | *(required)* |
| `META_WEBHOOK_VERIFY_TOKEN` | Token for webhook subscription verification | *(required)* |
| `META_GRAPH_API_VERSION` | Meta Graph API version | `v21.0` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `DATABASE_URL` | PostgreSQL connection string | *(required)* |
| `REDIS_URL` | Redis connection string | `redis://redis:6379/0` |
| `POSTGRES_USER` | PostgreSQL username | `postgres` |
| `POSTGRES_PASSWORD` | PostgreSQL password | `postgres` |
| `POSTGRES_DB` | PostgreSQL database name | `instagram_automation` |
| `JWT_SECRET` | Secret key for JWT signing | *(required)* |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | Access token expiry in minutes | `30` |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | Refresh token expiry in days | `7` |
| `TOKEN_ENCRYPTION_KEY` | Fernet key for encrypting Meta tokens | *(required)* |

## What's Not Included (Future Phases)

- Real Meta OAuth flow (structure ready with TODOs)
- Dashboard / frontend
- Multi-step conversations
- Story replies
- DM keyword automations
- AI replies
- Real token refresh (placeholder only)
- Redis caching logic
