# Instagram Comment-to-DM Automation

Self-hosted Instagram automation platform (ManyChat alternative). Keyword-triggered campaigns reply to Instagram comments with private DMs, then optionally hand the DM thread to an AI assistant that continues the conversation — using a Next.js dashboard, FastAPI backend, PostgreSQL, Redis, and Celery workers.

## Features

- **Keyword-triggered comment-to-DM campaigns** — match Instagram comments by keyword and send a private reply with templated variables.
- **Follow-gated delivery** — event-driven postback check that the commenter follows the account before the campaign message is released.
- **AI conversation continuation** — once a campaign DM is delivered, follow-up replies from the lead are picked up by an AI assistant instead of going unanswered:
  - Inbound DM webhook → dedup → lead lookup → conversation get-or-create → Celery chain.
  - AI scope and a shared daily message budget live at the `instagram_account` level (one business identity, one budget, shared across its campaigns).
  - Campaign-level opt-in toggle (`ai_enabled`) plus a per-campaign handoff-turn limit (`ai_handoff_after_turns`).
  - Guardrails: daily budget cap, turn limit, fail-closed error handling (a model or API error stops the reply rather than retrying blindly), and an echo guard that ignores the account's own outbound messages.
  - Vertical-specific, non-overridable safety instructions (e.g. clinical, real estate, restaurant) are injected into the system prompt per business type, regardless of what's in the configured business profile.
  - Conversations dashboard tab with a list/thread view and **Take Over** / **Resume Bot** actions for manual human handoff.

## Quick Start

1. Copy environment file:

```bash
cp .env.example .env
```

2. Generate a Fernet encryption key and add it to `.env`:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

2a. To use AI conversation continuation, add `OPENAI_API_KEY` to `.env`. Without it, AI replies fail closed (`no_api_key_configured`) and conversations stay unanswered until handed off manually.

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

The dashboard runs at:

```text
http://localhost:3000
```

Docker Compose starts it as the `dashboard` service with `NEXT_PUBLIC_API_URL=http://localhost:8000`.

## Marketing Dashboard

### Login flow

1. Start the stack and run migrations.
2. Create an admin user with `python -m app.scripts.create_admin` or the Docker command above.
3. Open `http://localhost:3000/login`.
4. Log in with the admin email and password. The MVP stores the access token in browser `localStorage`.

### Connecting a real Instagram account

From the dashboard, open `Accounts` and click the **Connect Instagram** button in the top right. This:

1. Calls `GET /meta/connect/start` to generate an OAuth URL with a CSRF state token (stored in Redis for 10 minutes).
2. Redirects your browser to the Meta OAuth dialog.
3. After you approve permissions, Meta redirects back to `/meta/connect/callback`.
4. The backend exchanges the authorization code for a long-lived token (60-day), fetches your Instagram Business account metadata, encrypts the token, and saves the account.
5. You are redirected back to `/accounts?connected=true` and the account appears in the table.

Requirements:
- A **Meta Business App** with the "Manage messaging & content on Instagram" use case.
- The user completing OAuth must be an admin of the Facebook Page linked to the Instagram Business account.
- The redirect URI `https://yourdomain.com/meta/connect/callback` must be registered in the Meta App dashboard.

### Mock connecting an account (development only)

In development (`NEXT_PUBLIC_APP_ENV != production`), the `Accounts` page shows a **Mock connect account** form. It calls:

```text
POST /meta/connect/mock
```

Use any local test values for `ig_user_id`, `username`, `account_type`, and `access_token`. This form is completely absent from production builds.

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
- `Conversations` lists AI-tracked DM threads by status, with a thread view and manual Take Over / Resume Bot controls.

### Running a dry webhook test

Use the signed webhook flow in `Webhook Comment Processing` below to send a local comment event. Then inspect `Overview`, `Logs`, `Leads`, and `Messages` in the dashboard.

### Enabling AI conversation continuation

Before testing AI replies end-to-end, both of the following must be turned on:

1. On the Instagram account (business identity level): set `business_vertical`, `ai_business_profile`, optional `ai_tone_instructions`, `ai_daily_message_cap`, and enable `ai_enabled`. This is the shared daily budget and safety scope for every AI-enabled campaign on that account.
2. On the campaign: enable `ai_enabled` and set `ai_handoff_after_turns` (the number of AI turns before the conversation is automatically handed off to a human).

With both enabled, a lead's DM reply after a campaign message triggers the webhook → dedup → lead lookup → conversation get-or-create → Celery chain, and the AI replies until it hits the turn limit, the account's daily budget cap, or a manual **Take Over** from the `Conversations` tab.

### Viewing and managing AI conversations

The `Conversations` tab lists every AI-tracked DM thread (filterable by status: `bot_active`, `handed_off`, `closed`), and clicking a row opens the full message thread. From an open thread, an operator can **Take Over** (pause the bot) or **Resume Bot** (hand it back to the AI).

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

### Real OAuth Flow

The full Meta OAuth flow is implemented end-to-end.

**Step 1 — Start OAuth**

```bash
GET /meta/connect/start
Authorization: Bearer <access_token>
```

Returns `{ "oauth_url": "https://www.facebook.com/v21.0/dialog/oauth?..." }`. Redirect the browser to this URL. A CSRF state token is stored in Redis for 10 minutes.

**Step 2 — Callback**

Meta redirects to:

```text
GET /meta/connect/callback?code=<code>&state=<state>
```

The backend:
1. Validates the `state` against Redis (one-time use, deleted immediately after check).
2. Exchanges `code` for a short-lived token via `POST https://graph.facebook.com/v21.0/oauth/access_token`.
3. Exchanges the short-lived token for a long-lived token (60 days) via `GET .../oauth/access_token?grant_type=fb_exchange_token`.
4. Calls `GET /me/accounts` to find linked Facebook Pages, then fetches the connected Instagram Business Account ID and username.
5. Upserts the `InstagramAccount` record, encrypts and stores the long-lived token.
6. Redirects to `{FRONTEND_URL}/accounts?connected=true`.

On any error, redirects to `{FRONTEND_URL}/accounts?error=oauth_failed`.

**Required Meta App setup**

| Setting | Value |
|---------|-------|
| App type | Business |
| Use case | Manage messaging & content on Instagram |
| Permissions | `instagram_business_basic`, `instagram_business_manage_messages`, `instagram_business_manage_comments`, `pages_show_list` |
| Valid OAuth redirect URI | `https://yourdomain.com/meta/connect/callback` |
| Webhook URL | `https://yourdomain.com/webhooks/meta` |
| Webhook fields | `comments`, `messaging_postbacks`, `messages` |

### Mock Account Connection (development only)

Use this endpoint to connect an account without going through Meta App Review. Only available when `APP_ENV=development`.

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

## Production Deployment

### Prerequisites

- VPS with Ubuntu 22.04+
- Docker and Docker Compose installed
- Domain DNS pointed to VPS IP
- Ports 80 and 443 open in firewall

### 1. Clone and configure

```bash
git clone https://github.com/YOUR_ORG/ManyOsirisChat.git
cd ManyOsirisChat
cp .env.production.example .env.production
nano .env.production   # fill in all real values
```

### 2. Generate required secret values

```bash
# JWT_SECRET and APP_SECRET_KEY (run twice, use separate values)
openssl rand -hex 32

# TOKEN_ENCRYPTION_KEY (Fernet format)
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# META_WEBHOOK_VERIFY_TOKEN
openssl rand -hex 32
```

### 3. Issue the first SSL certificate

```bash
docker compose -f docker-compose.prod.yml run --rm certbot certonly \
  --webroot -w /var/www/certbot \
  --email your@email.com \
  --agree-tos --no-eff-email \
  -d yourdomain.com
```

### 4. Start the stack

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Services started: `nginx`, `backend`, `dashboard`, `worker`, `beat`, `postgres`, `redis`, `certbot` (auto-renews every 12 hours).

### 5. Run migrations

```bash
docker compose -f docker-compose.prod.yml exec backend alembic upgrade head
```

### 6. Create admin user

```bash
docker compose -f docker-compose.prod.yml exec backend \
  python -m app.scripts.create_admin \
  --email owner@yourcompany.com \
  --password yourpassword \
  --name "Owner"
```

### 7. Register webhook in Meta App dashboard

| Field | Value |
|-------|-------|
| Callback URL | `https://yourdomain.com/webhooks/meta` |
| Verify Token | value of `META_WEBHOOK_VERIFY_TOKEN` from `.env.production` |
| Subscribed fields | `comments`, `messaging_postbacks`, `messages` (`messages` is required for AI conversation continuation) |

### 8. Register OAuth redirect URI in Meta App dashboard

```text
https://yourdomain.com/meta/connect/callback
```

### 9. Verify the stack

```bash
curl https://yourdomain.com/health
```

Expected response:

```json
{"status":"ok","service":"Instagram Automation","environment":"production","database":"ok"}
```

## Database

Migrations live in `backend/alembic/versions/` and run with `alembic upgrade head`. The AI conversation continuation layer is added by `0009_ai_conversation_layer.py`, which:

- Creates a `conversations` table (one row per lead+campaign AI thread: `status`, `handoff_reason`, `turn_count`, `last_message_at`).
- Extends `messages` with `direction` (`inbound`/`outbound`) and `conversation_id`.
- Extends `campaigns` with `ai_enabled` and `ai_handoff_after_turns`.
- Extends `instagram_accounts` with `business_vertical`, `ai_enabled`, `ai_business_profile`, `ai_tone_instructions`, `ai_daily_message_cap`, `ai_messages_sent_today`, and `ai_budget_reset_at`.

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
      routes_conversations.py # Conversation list/detail, take-over, resume-bot
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
      conversation.py        # Conversation model (AI conversation continuation)
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
        webhooks.py          # Signature verification & comment/postback/message parsers
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
      conversation_service.py # Conversation lifecycle & shared AI budget
      ai_service.py           # OpenAI system prompt & reply generation
    utils/
      crypto.py              # Fernet encryption utilities
      normalization.py       # Arabic & English text normalization
      templates.py           # Template variable extraction & rendering
    workers/
      celery_app.py          # Celery app configuration
      tasks.py               # Celery task implementations
      whatsapp_beat_schedule.py          # WhatsApp beat schedule
      instagram_token_beat_schedule.py   # Daily Instagram token refresh schedule
      instagram_token_tasks.py           # Instagram token refresh task
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
| `APP_BASE_URL` | Backend public URL (used in OAuth redirect URIs) | `http://localhost:8000` |
| `FRONTEND_URL` | Frontend URL for OAuth success/error redirects | `http://localhost:3000` |
| `ALLOWED_ORIGINS` | CORS allowed origins (comma-separated) | `http://localhost:3000` |
| `DISABLE_DOCS` | Disable FastAPI `/docs` and `/redoc` in production | `false` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `SENTRY_DSN` | Sentry error tracking DSN | *(optional)* |
| `META_APP_ID` | Meta App ID | `local_meta_app_id` |
| `META_APP_SECRET` | Meta App Secret — used for HMAC webhook verification and token exchange | *(required)* |
| `META_WEBHOOK_VERIFY_TOKEN` | Token for webhook subscription challenge verification | *(required)* |
| `META_GRAPH_API_VERSION` | Meta Graph API version | `v21.0` |
| `META_MOCK_PRIVATE_REPLIES` | Bypass real Meta API calls for message sending (dev only) | `false` |
| `AI_ENABLED_GLOBAL` | Global kill switch for AI conversation continuation, independent of per-account/campaign toggles | `true` |
| `OPENAI_API_KEY` | OpenAI API key used to generate AI conversation replies | *(required for AI replies)* |
| `AI_MODEL_NAME` | OpenAI model used for AI conversation replies | `gpt-4o-mini` |
| `AI_REQUEST_TIMEOUT_SECONDS` | Timeout for the OpenAI chat completion request | `15.0` |
| `AI_MAX_CONTEXT_TURNS` | Max prior messages included as conversation history per AI request | `10` |
| `DATABASE_URL` | PostgreSQL connection string | *(required)* |
| `REDIS_URL` | Redis connection string | `redis://redis:6379/0` |
| `POSTGRES_USER` | PostgreSQL username | `postgres` |
| `POSTGRES_PASSWORD` | PostgreSQL password | *(required)* |
| `POSTGRES_DB` | PostgreSQL database name | `instagram_automation` |
| `JWT_SECRET` | Secret key for JWT signing | *(required)* |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | Access token expiry in minutes | `30` |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | Refresh token expiry in days | `7` |
| `TOKEN_ENCRYPTION_KEY` | Fernet key for encrypting Meta access tokens at rest | *(required)* |
| `NEXT_PUBLIC_API_URL` | Backend URL used by the frontend at build time | `http://localhost:8000` |
| `NEXT_PUBLIC_APP_ENV` | Frontend environment — set to `production` to hide dev-only UI | `development` |
| `BACKUP_DIR` | Directory for database backup files | `./backups` |

## Roadmap

### v1 — Complete
- Real Meta OAuth with encrypted long-lived token storage
- Instagram Business account connection via OAuth
- Keyword-triggered campaign automation
- Follow prompt flow
- Event-driven postback follow verification gate before releasing the campaign message
- Target media (any media or specific post/reel)
- Lead capture and CSV export
- Message delivery tracking with retry
- Role-based access control (Owner, Admin, Operator, Viewer)
- Rate limiting and HMAC webhook verification
- Audit logging
- Production Docker + Nginx + SSL infrastructure
- AI conversation continuation (account-level AI scope and shared daily budget, campaign-level opt-in and handoff-turn limit, vertical-specific safety instructions, Conversations dashboard tab)

### Planned
- WhatsApp Business Platform integration (separate future phase — its own Meta app product and App Review, plus a new `platform` field on leads)
