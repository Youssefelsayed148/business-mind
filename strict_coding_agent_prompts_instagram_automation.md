# Strict Coding-Agent Prompts — Instagram Comment-to-DM Automation

These prompts are designed to be pasted into a coding agent phase by phase.  
They are intentionally strict so the agent does not improvise architecture, skip security requirements, or build future phases too early.

Project source of truth:
- Python FastAPI backend
- PostgreSQL
- Redis
- Celery
- Next.js dashboard
- Docker-first local development
- Meta official APIs only
- No scraping, no browser automation, no username/password Instagram login

---

# Global Rules for Every Coding Agent Phase

Paste this before every phase prompt.

```txt
You are working on an Instagram Comment-to-DM automation product.

Important global rules:
1. Follow the existing architecture. Do not replace FastAPI, PostgreSQL, Redis, Celery, SQLAlchemy, Alembic, or Next.js unless explicitly instructed.
2. Do not build features from future phases.
3. Do not use scraping, Selenium, Playwright, unofficial Instagram APIs, browser automation, or Instagram username/password login.
4. Use only Meta official APIs.
5. Keep everything Docker-first and runnable locally.
6. Prefer small, testable changes.
7. Add or update README instructions whenever commands change.
8. Add tests for every service-level function.
9. Never store access tokens in plaintext.
10. Never send messages synchronously inside the webhook HTTP request.
11. Webhook POST must read the raw request body before parsing JSON.
12. Webhook POST must verify X-Hub-Signature-256 before accepting the event.
13. Webhook handlers must return quickly and process work asynchronously.
14. Use environment variables through pydantic-settings.
15. Do not hardcode secrets.
16. Use structured logs.
17. Make database changes through Alembic migrations.
18. Add idempotency constraints when new event/message flows are added.
19. Keep code organized under the folder structure already defined.
20. After finishing, output:
   - files changed
   - commands to run
   - tests added
   - manual verification steps
   - known limitations
```

---

# Phase 0 — Local FastAPI + Meta Webhook Validation Foundation

## Prompt

```txt
You are building Phase 0 of the Instagram Comment-to-DM automation product.

Objective:
Create the minimal local Dockerized FastAPI foundation needed to validate Meta webhook verification and webhook POST security.

Current target:
Local development only through Docker and localhost.

Tech:
- Python 3.11+
- FastAPI
- uvicorn
- pydantic-settings
- Docker
- Docker Compose
- pytest

Required folder structure:

backend/
  app/
    main.py
    core/
      config.py
      logging.py
    api/
      routes_webhooks.py
      routes_health.py
    integrations/
      meta/
        webhooks.py
  tests/
    test_health.py
    test_meta_webhooks.py
  requirements.txt
  Dockerfile

Root:
  docker-compose.yml
  .env.example
  README.md
  .gitignore

Implement:

1. Settings
File: backend/app/core/config.py

Create a Settings class using pydantic-settings with:
- APP_ENV: str = "development"
- APP_NAME: str = "Instagram Automation"
- META_APP_SECRET: str
- META_WEBHOOK_VERIFY_TOKEN: str
- META_GRAPH_API_VERSION: str = "v21.0"
- LOG_LEVEL: str = "INFO"

Expose:
- settings = Settings()

2. Logging
File: backend/app/core/logging.py

Implement simple structured JSON logging setup.
At minimum, logs should include:
- timestamp
- level
- logger
- message

3. FastAPI app
File: backend/app/main.py

Create FastAPI app.
Include routers:
- health router
- webhook router

Add root endpoint:
GET /
Response:
{
  "service": "Instagram Automation",
  "status": "running"
}

4. Health endpoint
File: backend/app/api/routes_health.py

GET /health
Response:
{
  "status": "ok",
  "service": "Instagram Automation",
  "environment": "development"
}

5. Meta webhook verification
File: backend/app/api/routes_webhooks.py

GET /webhooks/meta

Read query params exactly:
- hub.mode
- hub.verify_token
- hub.challenge

Rules:
- if hub.mode == "subscribe" AND hub.verify_token == settings.META_WEBHOOK_VERIFY_TOKEN:
    return hub.challenge as plain text, HTTP 200
- otherwise return HTTP 403

6. Webhook POST
File: backend/app/api/routes_webhooks.py

POST /webhooks/meta

Rules:
- read raw body bytes first
- read X-Hub-Signature-256 header
- call verify_meta_signature from integrations/meta/webhooks.py
- if signature invalid: return 403
- if valid: parse JSON payload
- log payload summary
- return {"status": "received"} immediately
- do not process campaign logic
- do not send messages
- do not store database events yet

7. Signature verification utility
File: backend/app/integrations/meta/webhooks.py

Implement:

verify_meta_signature(raw_body: bytes, signature_header: str | None, app_secret: str) -> bool

Rules:
- signature header format must be: sha256=<hex_digest>
- compute HMAC SHA256 using app_secret over raw_body
- compare using hmac.compare_digest
- return False for missing/malformed signature
- include tests

8. Docker
File: backend/Dockerfile

Use python:3.11-slim.
Install requirements.
Run uvicorn:
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

File: docker-compose.yml

Create service:
backend:
  build: ./backend
  ports:
    - "8000:8000"
  env_file:
    - .env
  volumes:
    - ./backend:/app

9. .env.example

Include:
APP_ENV=development
APP_NAME=Instagram Automation
META_APP_SECRET=local_meta_app_secret
META_WEBHOOK_VERIFY_TOKEN=local_verify_token_123
META_GRAPH_API_VERSION=v21.0
LOG_LEVEL=INFO

10. Tests

Add tests:
- GET /health returns 200 and status ok
- GET /webhooks/meta with correct token returns challenge
- GET /webhooks/meta with wrong token returns 403
- verify_meta_signature returns True for valid signature
- verify_meta_signature returns False for invalid signature
- POST /webhooks/meta rejects missing signature
- POST /webhooks/meta accepts valid signature

11. README

Document:
- cp .env.example .env
- docker compose up --build
- curl http://localhost:8000/health
- curl verification challenge test
- how to generate X-Hub-Signature-256 for local POST testing

Do not implement:
- PostgreSQL
- Redis
- Celery
- Alembic
- OAuth
- Campaigns
- Message sending
- Dashboard

Acceptance criteria:
- docker compose up --build starts backend.
- GET /health works.
- Webhook GET challenge works.
- Webhook POST signature validation works.
- pytest passes inside container.
```

---

# Phase 1 — Backend Foundation: Database, Models, Auth, Migrations

## Prompt

```txt
You are building Phase 1 of the Instagram Comment-to-DM automation product.

Objective:
Add the backend foundation: PostgreSQL, Redis, SQLAlchemy models, Alembic migrations, auth, admin creation, and structured logging.

Use the existing Phase 0 code. Do not rewrite it.

Tech:
- FastAPI
- PostgreSQL 15
- Redis 7
- SQLAlchemy 2.x
- Alembic
- psycopg
- Pydantic v2
- pydantic-settings
- passlib[argon2] or argon2-cffi
- python-jose or PyJWT
- pytest

Required new/updated folder structure:

backend/app/
  db/
    base.py
    session.py
  models/
    user.py
    workspace.py
    instagram_account.py
    meta_token.py
    campaign.py
    campaign_keyword.py
    webhook_event.py
    comment.py
    lead.py
    message.py
    automation_log.py
    user_cooldown.py
    webhook_health.py
  schemas/
    auth.py
    user.py
  api/
    routes_auth.py
  core/
    security.py
  scripts/
    create_admin.py

backend/alembic/
backend/alembic.ini

Implement:

1. Docker Compose update

Add services:
- postgres
- redis

docker-compose.yml must include:
postgres:
  image: postgres:15
  environment from .env:
    POSTGRES_USER
    POSTGRES_PASSWORD
    POSTGRES_DB
  ports:
    - "5432:5432"
  volumes:
    - pgdata:/var/lib/postgresql/data

redis:
  image: redis:7-alpine
  ports:
    - "6379:6379"
  volumes:
    - redisdata:/data

backend depends_on:
- postgres
- redis

2. Environment variables

Update .env.example:

DATABASE_URL=postgresql+psycopg://postgres:postgres@postgres:5432/instagram_automation
REDIS_URL=redis://redis:6379/0
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=instagram_automation

JWT_SECRET=change_me_local_jwt_secret
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

APP_SECRET_KEY=change_me_local_app_secret

3. Database session

File: backend/app/db/session.py

Create SQLAlchemy engine from DATABASE_URL.
Create SessionLocal.
Create get_db dependency.

Use SQLAlchemy 2.x style.

4. Base

File: backend/app/db/base.py

Create DeclarativeBase class.
Import all models so Alembic can detect them.

5. Models

Create models matching the plan.

Use UUID primary keys.
Use datetime columns.
Use JSONB for PostgreSQL metadata/payload fields.
Use ARRAY/Text[] where appropriate, or JSONB if simpler and consistent.
Add unique constraints:

users:
- email unique

workspaces:
- slug unique

instagram_accounts:
- ig_user_id unique

campaign_keywords:
- unique campaign_id + normalized_keyword

webhook_events:
- unique provider + external_event_id

comments:
- comment_id unique

leads:
- unique workspace_id + instagram_account_id + instagram_user_id

messages:
- unique campaign_id + comment_id

user_cooldowns:
- unique campaign_id + instagram_user_id

Important statuses:
Campaign.status: draft, active, paused, archived
Message.status: queued, sending, sent, failed, expired, skipped, cooldown
Token.status: active, expiring_soon, expired
WebhookEvent.processing_status: pending, processed, skipped, failed

6. Alembic

Initialize Alembic.
Configure env.py to use app.db.base.Base.metadata.
Create initial migration.
The migration must create all tables and constraints.

7. Health endpoint update

GET /health should return:
{
  "status": "ok",
  "service": "...",
  "environment": "...",
  "database": "ok"
}

If database fails:
- return HTTP 503
- database: "error"

8. Auth security

File: backend/app/core/security.py

Implement:
- hash_password(password: str) -> str
- verify_password(password: str, password_hash: str) -> bool
- create_access_token(subject: str, expires_delta: timedelta | None = None) -> str
- decode_access_token(token: str) -> dict

9. Auth schemas

File: backend/app/schemas/auth.py

Create:
- LoginRequest { email, password }
- TokenResponse { access_token, token_type }
- MeResponse { id, email, name, role }

10. Auth routes

File: backend/app/api/routes_auth.py

POST /auth/login
- accepts email/password
- verifies user exists and is_active
- returns JWT bearer access token

GET /auth/me
- requires Authorization: Bearer token
- returns current user

POST /auth/logout
- stateless for MVP
- returns {"status": "ok"}

Do not implement refresh token yet unless already easy.
Keep auth simple for Phase 1.

11. Create admin script

File: backend/app/scripts/create_admin.py

CLI usage:
python -m app.scripts.create_admin --email admin@example.com --password admin123 --name "Admin"

Rules:
- create default workspace if none exists:
  name: Default Workspace
  slug: default
- create admin user
- if user exists, print message and do not duplicate

12. Tests

Add tests:
- database health success
- password hashing/verification
- JWT encode/decode
- create admin script creates user
- login returns token
- /auth/me returns user
- duplicate workspace slug is rejected
- duplicate user email is rejected

13. README update

Document:
- docker compose up --build
- docker compose exec backend alembic upgrade head
- docker compose exec backend python -m app.scripts.create_admin --email admin@example.com --password admin123 --name Admin
- login curl command
- /auth/me curl command

Do not implement:
- Meta OAuth
- Token encryption
- Campaign CRUD
- Webhook database storage beyond the model
- Celery workers
- Dashboard

Acceptance criteria:
- docker compose up starts backend, postgres, redis.
- alembic upgrade head creates all tables.
- admin can be created.
- login works.
- /auth/me works.
- tests pass.
```

---

# Phase 2 — Meta Integration, Token Encryption, Webhook Persistence, Celery Skeleton

## Prompt

```txt
You are building Phase 2 of the Instagram Comment-to-DM automation product.

Objective:
Implement Meta integration foundations: encrypted token storage, Instagram account connection service structure, webhook event persistence, deduplication, Celery skeleton, and token status jobs.

Use the existing Phase 1 code. Do not rewrite the app.

Important:
This phase does not send Instagram messages yet.
This phase does not process campaigns yet.

New/updated folders:

backend/app/
  integrations/
    meta/
      client.py
      oauth.py
      accounts.py
      webhooks.py
      errors.py
  services/
    token_service.py
    webhook_event_service.py
  workers/
    celery_app.py
    tasks.py
    beat_schedule.py
  utils/
    crypto.py

Implement:

1. Environment variables

Update .env.example:
TOKEN_ENCRYPTION_KEY=
META_APP_ID=local_meta_app_id
META_APP_SECRET=local_meta_app_secret
META_WEBHOOK_VERIFY_TOKEN=local_verify_token_123
META_GRAPH_API_VERSION=v21.0
APP_BASE_URL=http://localhost:8000

Add README command:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

2. Token encryption

File: backend/app/utils/crypto.py

Implement:
- encrypt_text(plain_text: str) -> str
- decrypt_text(encrypted_text: str) -> str

Use Fernet with TOKEN_ENCRYPTION_KEY.

Tests:
- encrypt/decrypt roundtrip
- encrypted output is not equal to plaintext
- invalid key or invalid token raises controlled error

3. Meta HTTP client

File: backend/app/integrations/meta/client.py

Create MetaGraphClient.

Use httpx.AsyncClient.

Methods:
- get(path: str, access_token: str, params: dict | None = None)
- post(path: str, access_token: str, json: dict | None = None, params: dict | None = None)

Base URL:
https://graph.facebook.com/{META_GRAPH_API_VERSION}
or configurable according to endpoint needs.

For now, tests should mock httpx.

Do not hardcode API version.

4. Meta OAuth structure

File: backend/app/integrations/meta/oauth.py

Implement service functions but keep adaptable:

- build_oauth_url(state: str) -> str
- exchange_code_for_short_lived_token(code: str) -> dict
- exchange_for_long_lived_token(short_lived_token: str) -> dict

Use environment:
- META_APP_ID
- META_APP_SECRET
- APP_BASE_URL

Callback URL:
{APP_BASE_URL}/meta/connect/callback

Important:
If real Meta OAuth details are not fully confirmed yet, implement clean structure with TODO comments and testable URL generation.
Do not fake production behavior silently.

5. Account service

File: backend/app/integrations/meta/accounts.py

Implement:
- fetch_instagram_account_metadata(access_token: str) -> dict

Expected output shape:
{
  "ig_user_id": "...",
  "username": "...",
  "account_type": "BUSINESS" | "CREATOR",
  "profile_picture_url": "..."
}

For tests, mock Meta API.

6. Token service

File: backend/app/services/token_service.py

Implement:
- store_encrypted_token(db, workspace_id, instagram_account_id, access_token, scopes, expires_at)
- get_decrypted_token(db, instagram_account_id)
- mark_token_expiring_soon(db, token_id)
- mark_token_expired(db, token_id)
- get_tokens_expiring_within(db, days: int)
- refresh_token_placeholder(db, token_id)

Do not implement real refresh if endpoint is not confirmed.
But structure the function and log that it is placeholder.

7. Meta connection routes

Add routes in backend/app/api/routes_meta.py

GET /meta/connect/start
- requires auth
- creates state token
- returns { "oauth_url": "..." }

GET /meta/connect/callback
- receives code and state
- exchanges code
- stores encrypted token
- fetches account metadata
- upserts instagram_accounts
- returns success JSON

For local dev:
Add POST /meta/connect/mock only in APP_ENV=development
- requires auth
- accepts:
  ig_user_id
  username
  account_type
  access_token
  expires_at
- encrypts token
- creates instagram account
This lets us continue local development before App Review.

8. Instagram account routes

Add:
GET /instagram/accounts
GET /instagram/accounts/{id}
POST /instagram/accounts/{id}/reconnect
DELETE /instagram/accounts/{id}
GET /instagram/accounts/{id}/health

Rules:
- all require auth
- MVP workspace can be default workspace
- DELETE should mark disconnected, not hard delete

9. Webhook POST persistence

Update POST /webhooks/meta:

Rules:
- verify signature first
- parse payload after signature passes
- derive external_event_id

external_event_id strategy:
- If payload contains a clear event/comment/message id, use it.
- Otherwise compute deterministic sha256 hash of raw body.
- Store provider="meta", external_event_id, event_type, payload, signature_valid=True.
- If duplicate unique constraint occurs, return {"status": "duplicate"} with 200.
- Do not process campaign logic yet.
- Do not send messages.
- Return quickly.

10. Webhook event service

File: backend/app/services/webhook_event_service.py

Implement:
- derive_external_event_id(payload: dict, raw_body: bytes) -> str
- derive_event_type(payload: dict) -> str
- store_webhook_event(db, payload, raw_body, signature_valid) -> WebhookEvent
- mark_webhook_event_processed/skipped/failed

11. Celery setup

File: backend/app/workers/celery_app.py

Create Celery app using REDIS_URL.

File: backend/app/workers/beat_schedule.py

Create schedule placeholders:
- check_token_expiry daily
- refresh_expiring_tokens daily
- webhook_health_check hourly

File: backend/app/workers/tasks.py

Implement placeholder tasks:
- check_token_expiry
- refresh_expiring_tokens
- webhook_health_check

Update docker-compose.yml:
Add worker:
command: celery -A app.workers.celery_app worker --loglevel=info

Add beat:
command: celery -A app.workers.celery_app beat --loglevel=info

12. Tests

Add tests:
- token encryption roundtrip
- mock Meta connect creates account and encrypted token
- token is not plaintext in DB
- list instagram accounts
- webhook POST stores event
- duplicate webhook POST does not duplicate event
- invalid webhook signature rejected
- external_event_id fallback hash is deterministic
- Celery app imports successfully

13. README update

Document:
- generate Fernet key
- use /meta/connect/mock locally
- webhook POST storage test
- start worker/beat with docker compose

Do not implement:
- Campaign CRUD
- Keyword matching
- Message sending
- Lead creation
- Dashboard UI

Acceptance criteria:
- Local mock account connection works.
- Tokens are encrypted.
- Webhook events are persisted.
- Duplicate webhook events are deduped.
- Worker and beat containers start.
- Tests pass.
```

---

# Phase 3 — Campaign Engine, Keyword Normalization, Templates, Simulation

## Prompt

```txt
You are building Phase 3 of the Instagram Comment-to-DM automation product.

Objective:
Build the complete campaign management and matching engine without sending real Instagram messages yet.

Use existing Phase 2 code.

New/updated folders:

backend/app/
  services/
    campaign_service.py
    campaign_matcher.py
    template_service.py
    cooldown_service.py
  utils/
    normalization.py
    templates.py
  schemas/
    campaign.py

Implement:

1. Campaign schemas

File: backend/app/schemas/campaign.py

Create Pydantic schemas:
- CampaignCreate
- CampaignUpdate
- CampaignResponse
- CampaignKeywordCreate
- CampaignKeywordResponse
- CampaignSimulateRequest
- CampaignSimulateResponse

Fields:
CampaignCreate:
- instagram_account_id: UUID
- name: str
- description: str | None
- media_id: str
- media_url: str | None
- match_type: Literal["contains", "exact", "starts_with"]
- message_template: str
- link_url: str | None
- cooldown_hours: int = 168
- status: Literal["draft", "active", "paused"] = "draft"
- keywords: list[str]

Validation:
- name required, non-empty
- message_template required, non-empty
- message_template max 1000 chars after rendering warning/validation
- media_id required for MVP
- keywords required unless match_type future any_comment, which is not MVP
- cooldown_hours >= 0
- no unknown template variables

2. Normalization

File: backend/app/utils/normalization.py

Implement:
- strip_emojis(text: str) -> str
- normalize_arabic(text: str) -> str
- normalize_english(text: str) -> str
- normalize_comment(text: str) -> str

Rules:
English:
- lowercase
- trim
- collapse whitespace
- strip surrounding punctuation
- remove emojis

Arabic:
- normalize أ إ آ ا to ا
- normalize ة to ه
- remove tashkeel/diacritics
- normalize ي ى to ي
- normalize ؤ و to و only if this does not break normal words too aggressively
- trim
- collapse whitespace
- remove emojis

Tests:
- "PROMPT!!" => "prompt"
- " Ai " => "ai"
- "Claude🔥" => "claude"
- "بُرومبت" matches "برومبت"
- Arabic alef variants normalize consistently

3. Template system

File: backend/app/utils/templates.py

Allowed variables:
- username
- campaign_name
- keyword
- link
- media_url

Implement:
- extract_template_variables(template: str) -> set[str]
- validate_template(template: str) -> None
- render_template(template: str, context: dict) -> str

Rules:
- unknown variables raise validation error
- missing context values use safe fallbacks:
  username -> "there"
  link -> ""
  media_url -> ""
  keyword -> ""
- rendered message cannot be empty
- rendered message should not exceed 1000 chars
- store rendered body later in messages table

4. Keyword matching

File: backend/app/services/campaign_matcher.py

Implement:
- keyword_matches(comment_text: str, keyword: str, match_type: str) -> bool
- find_matching_keyword(comment_text: str, normalized_keywords: list[str], match_type: str) -> str | None
- find_matching_campaigns(db, instagram_account_id, media_id, comment_text) -> list[MatchResult]

Rules:
- only campaigns with status active match real events
- media_id must match exactly for MVP
- contains: normalized keyword substring in normalized comment
- exact: normalized comment == normalized keyword
- starts_with: normalized comment.startswith(normalized_keyword)
- return matched keyword

Create MatchResult dataclass:
- campaign_id
- matched_keyword
- rendered_message_preview maybe optional

5. Campaign service

File: backend/app/services/campaign_service.py

Implement:
- create_campaign(db, workspace_id, payload)
- update_campaign
- get_campaign
- list_campaigns
- activate_campaign
- pause_campaign
- archive_campaign
- add_keyword
- delete_keyword

Rules:
- normalize keywords at write time
- prevent duplicate normalized keyword per campaign
- validate template before save
- cannot activate campaign if:
  - no keywords
  - message_template invalid
  - instagram account not connected
  - media_id missing
- archive should not hard delete

6. Campaign routes

File: backend/app/api/routes_campaigns.py

Implement:
GET /campaigns
POST /campaigns
GET /campaigns/{id}
PATCH /campaigns/{id}
DELETE /campaigns/{id}
POST /campaigns/{id}/activate
POST /campaigns/{id}/pause
POST /campaigns/{id}/archive
GET /campaigns/{id}/keywords
POST /campaigns/{id}/keywords
DELETE /campaigns/{id}/keywords/{keyword_id}
POST /campaigns/{id}/simulate

All require auth.

7. Simulate endpoint

POST /campaigns/{id}/simulate

Input:
{
  "comment_text": "I want the prompt",
  "username": "Ahmed"
}

Output:
{
  "matched": true,
  "matched_keyword": "prompt",
  "rendered_message": "Hey Ahmed..."
}

Rules:
- allow simulation for draft/paused/active campaigns
- does not create comment, lead, message, or log records
- no Meta API calls

8. Activity logs

When campaign is created/activated/paused/archived, create automation_logs entry.

9. Tests

Add tests:
- create campaign with keywords
- duplicate normalized keyword rejected
- invalid template variable rejected
- activate fails with no keywords
- activate fails with disconnected account
- contains match
- exact match
- starts_with match
- Arabic normalization match
- simulate returns rendered message
- paused campaign does not match in find_matching_campaigns
- draft campaign does not match real matching

10. README update

Add campaign create curl examples and simulate example.

Do not implement:
- Real message sending
- Webhook comment parsing
- Lead creation
- Dashboard UI
- Any-post campaigns

Acceptance criteria:
- Campaign CRUD works.
- Keyword normalization works for Arabic and English.
- Simulation works.
- Active campaign matching works.
- Draft/paused campaigns do not match real comments.
- Tests pass.
```

---

# Phase 4 — Webhook Comment Processing, Leads, Messaging Worker

## Prompt

```txt
You are building Phase 4 of the Instagram Comment-to-DM automation product.

Objective:
Connect real webhook comment events to campaign matching, lead creation, Celery queue, and Meta private reply sending.

Use existing Phase 3 code.

Critical:
- Never send messages inside the webhook HTTP handler.
- Enforce idempotency before queueing or sending.
- Enforce cooldown before sending.
- Store all steps in automation_logs.
- Use official Meta API only.

New/updated folders:

backend/app/
  services/
    comment_service.py
    lead_service.py
    message_service.py
    cooldown_service.py
    log_service.py
  integrations/
    meta/
      messaging.py
      errors.py
  workers/
    tasks.py

Implement:

1. Meta comment event parser

File: backend/app/integrations/meta/webhooks.py

Add:
- parse_instagram_comment_events(payload: dict) -> list[ParsedCommentEvent]

ParsedCommentEvent fields:
- instagram_account_ig_user_id
- media_id
- comment_id
- commenter_ig_id
- username optional
- comment_text
- created_time optional
- raw_event

Important:
Meta webhook payload shapes may vary.
Implement parser defensively:
- return empty list if not a comment event
- do not crash on missing optional fields
- log unknown shapes
- keep raw payload stored

2. Webhook processing flow

Update POST /webhooks/meta:
- verify signature
- store webhook_event
- if duplicate: return 200 duplicate
- enqueue Celery task process_webhook_event(webhook_event_id)
- return 200 immediately

Do not process event inline.

3. Celery task: process_webhook_event

File: backend/app/workers/tasks.py

Implement task:
process_webhook_event(webhook_event_id: str)

Flow:
1. Load webhook_event.
2. Parse comment events.
3. For each comment event:
   a. store comment using comment_service
   b. find instagram_accounts by ig_user_id
   c. find active matching campaigns
   d. for each match:
      - check message idempotency campaign_id + comment_id
      - check cooldown
      - render message
      - upsert lead
      - create message row with status queued
      - create automation log message_queued
      - enqueue send_private_reply(message_id)
4. Mark webhook_event processed.
5. If parser returns no events, mark skipped.

4. Comment service

File: backend/app/services/comment_service.py

Implement:
- upsert_comment(db, parsed_event, instagram_account_id)

Rules:
- comment_id unique
- if duplicate, return existing comment and flag duplicate
- store normalized_text
- store received_at

5. Lead service

File: backend/app/services/lead_service.py

Implement:
- upsert_lead_from_comment(db, workspace_id, instagram_account_id, campaign_id, parsed_event, matched_keyword)

Rules:
- unique workspace + instagram_account + instagram_user_id
- first_seen_at preserved
- last_seen_at updated
- source campaign/comment updated on latest trigger
- status defaults to new

6. Cooldown service

File: backend/app/services/cooldown_service.py

Implement:
- is_in_cooldown(db, campaign_id, instagram_user_id, cooldown_hours) -> bool
- record_cooldown(db, campaign_id, instagram_user_id)

Rules:
- if cooldown_hours == 0, no cooldown
- update last_triggered_at after successful queueing or successful send?
Decision:
Record cooldown when message is queued to prevent duplicate queue sends.
If send fails permanently, manual retry should still be possible from message row.

7. Message service

File: backend/app/services/message_service.py

Implement:
- create_queued_message(...)
- mark_message_sending
- mark_message_sent(provider_message_id)
- mark_message_failed(error_code, error_message, retryable)
- mark_message_expired(error_code, error_message)
- mark_message_skipped(reason)
- get_message_for_send(message_id)

Rules:
- unique campaign_id + comment_id
- store rendered_message_body
- status transitions must be clear

8. Meta messaging client

File: backend/app/integrations/meta/messaging.py

Implement:
- send_private_reply(access_token: str, comment_id: str, text: str) -> MetaMessageResult

Use official endpoint structure from config.
Do not hardcode API version.
Use httpx.
Return:
- success: bool
- provider_message_id optional
- raw_response
- error_code optional
- error_message optional

Keep endpoint configurable if Meta endpoint path differs.

9. Meta error classification

File: backend/app/integrations/meta/errors.py

Implement:
- classify_meta_error(status_code: int, response_json: dict) -> ErrorClassification

Categories:
- retryable
- token_error
- permission_error
- policy_error
- expired_private_reply
- user_unreachable
- invalid_reference
- unknown_non_retryable

Rules:
Retryable:
- network timeout
- HTTP 5xx
- HTTP 429

Non-retryable:
- invalid/expired token
- missing permission
- policy violation
- comment too old/private reply expired
- invalid comment_id/media_id

10. Celery task: send_private_reply

Implement task:
send_private_reply(message_id: str)

Flow:
1. Load message with campaign, lead, instagram account.
2. If campaign no longer active, mark skipped.
3. Get decrypted token.
4. Mark message sending.
5. Call Meta messaging client.
6. If success:
   - mark sent
   - record cooldown
   - increment campaign successful_sends
   - log message_sent
7. If expired private reply:
   - mark expired
   - do not retry
   - log message_expired
8. If retryable:
   - mark failed with retryable flag
   - retry with exponential backoff max 4
9. If token/permission/policy:
   - mark failed
   - pause campaigns for account only if token/permission issue
   - log clear dashboard-friendly error
   - do not retry

11. Campaign counters

Update:
- total_triggers when match is confirmed
- successful_sends on sent
- failed_sends on permanent failed

12. Logs

Use automation_logs for:
- webhook_received
- webhook_duplicate
- campaign_matched
- campaign_no_match
- cooldown_skip
- message_queued
- message_sending
- message_sent
- message_failed
- message_expired
- message_policy_error
- token_expired

13. Message retry endpoint

Add:
POST /messages/{id}/retry

Rules:
- requires auth
- only statuses failed can be retried
- expired cannot be retried
- sent cannot be retried
- creates/enqueues send_private_reply for same message
- increments retry_count through task

Add:
GET /messages
GET /messages/{id}

14. Tests

Add tests:
- webhook event queues process_webhook_event
- parser returns comment event for sample payload
- non-comment payload is skipped
- comment creates comment row
- matching active campaign creates queued message
- duplicate webhook does not create duplicate message
- duplicate comment does not create duplicate message
- cooldown prevents message queue
- lead is created
- message is sent successfully with mocked Meta API
- retryable Meta 500 retries
- expired private reply marked expired and not retried
- token error marks failed and does not retry
- retry endpoint rejects sent/expired messages
- retry endpoint accepts failed message

15. README update

Document:
- how to send a sample signed webhook POST locally
- how to run worker
- how to inspect messages/logs
- how to test with mocked Meta API

Do not implement:
- Dashboard UI
- Multi-step conversations
- Story replies
- DM keyword automations
- AI replies

Acceptance criteria:
- Valid signed comment webhook can create a message job.
- Exactly one message per campaign/comment is created.
- Cooldown works.
- Lead is created.
- Mocked Meta success marks message sent.
- Expired/private reply error is not retried.
- Tests pass.
```

---

# Phase 5 — Next.js Marketing Dashboard MVP

## Prompt

```txt
You are building Phase 5: Marketing Dashboard MVP.

Objective:
Build the internal dashboard so a non-technical marketing team can operate the automation.

Use:
- Next.js 14+ App Router
- TypeScript
- Tailwind CSS
- Existing FastAPI API
- Docker Compose

Do not change backend behavior unless a small endpoint is missing for dashboard needs.

Required dashboard structure:

dashboard/
  app/
    (auth)/
      login/page.tsx
    (dashboard)/
      layout.tsx
      overview/page.tsx
      accounts/page.tsx
      campaigns/page.tsx
      campaigns/new/page.tsx
      campaigns/[id]/page.tsx
      campaigns/[id]/stats/page.tsx
      leads/page.tsx
      logs/page.tsx
      messages/page.tsx
  components/
    ui/
    layout/
    campaigns/
    accounts/
    leads/
    logs/
    activity/
  lib/
    api.ts
    auth.ts
    types.ts
  Dockerfile
  package.json

Implement:

1. Docker

Add dashboard service to docker-compose.yml:
- build ./dashboard
- port 3000:3000
- env NEXT_PUBLIC_API_URL=http://localhost:8000

2. API client

File: dashboard/lib/api.ts

Implement:
- get
- post
- patch
- delete
- auth bearer token injection
- redirect to login on 401
- human-readable error extraction

3. Auth

Login page:
- email
- password
- submit
- call POST /auth/login
- store access token in localStorage for MVP
- redirect to overview

Dashboard layout:
- check token
- call /auth/me
- sidebar navigation
- logout button clears token

4. Overview page

Show cards:
- Active campaigns
- Triggers today
- Messages sent
- Failed messages
- New leads

If backend stats endpoint missing, add minimal backend endpoint:
GET /stats/overview

Return:
{
  active_campaigns,
  triggers_today,
  messages_sent_today,
  failed_messages_today,
  new_leads_today
}

Activity feed:
- poll GET /logs?limit=20 every 5 seconds
- show icon, time, campaign, event_type, message

5. Accounts page

Use:
GET /instagram/accounts

Show:
- username
- account type
- status
- token expiry warning if available
- last active/connected date
- reconnect button placeholder
- disconnect button if backend exists

In development, add small UI section:
"Mock connect account"
Fields:
- ig_user_id
- username
- account_type
- access_token
- expires_at
Calls /meta/connect/mock
Only show if NEXT_PUBLIC_APP_ENV=development.

6. Campaigns list

Use:
GET /campaigns

Show table:
- name
- account username/id
- media_id/media_url
- keywords
- status badge
- total triggers
- successful sends
- failed sends
- actions: Edit, Activate/Pause, Archive, Stats

7. Campaign create/edit

Build step-style form:
Step 1:
- name
- description
- instagram_account_id

Step 2:
- media_id
- media_url

Step 3:
- keywords dynamic input
- match_type contains/exact/starts_with

Step 4:
- message_template textarea
- variable insert buttons:
  {{username}}
  {{campaign_name}}
  {{keyword}}
  {{link}}
  {{media_url}}
- link_url
- character count

Step 5:
- cooldown_hours
- status draft/active

Buttons:
- Save Draft
- Activate Campaign
- Test Message

Test Message modal:
- comment_text
- username
- calls POST /campaigns/{id}/simulate after saving draft OR if unsaved, use backend endpoint if available
- show matched true/false
- show rendered message

If simulation requires existing campaign, implement flow:
- Save draft first
- Then simulate

8. Campaign detail/stats page

Show:
- total triggers
- successful sends
- failed sends
- expired
- cooldowns
- recent messages/logs
- retry failed button if backend supports

If backend stats missing:
Add GET /campaigns/{id}/stats.

9. Leads page

Use:
GET /leads

If backend missing, implement backend endpoints:
GET /leads
GET /leads/export.csv

Table:
- username
- source campaign
- keyword
- status
- tags
- first seen
- last seen

Filters:
- campaign
- status
- search username

Export CSV button.

10. Logs page

Use:
GET /logs

If backend missing, implement:
GET /logs?level=&campaign_id=&event_type=&limit=

Show:
- level
- time
- campaign
- event type
- message
- metadata expandable

11. Messages page

Use:
GET /messages

Show:
- status
- campaign
- username/lead
- comment_id
- retry_count
- sent_at
- error message
- retry button for failed only

12. Human-readable statuses

Use text labels:
- Active
- Draft
- Paused
- Archived
- Connected
- Expiring Soon
- Reconnect Required
- Sent
- Failed
- Expired
- Cooldown

Do not rely on color alone.

13. Tests or basic quality

At minimum:
- TypeScript builds
- npm run lint passes if lint configured
- no hardcoded API URL except env
- no secret values in code

14. README update

Document:
- dashboard local URL
- login flow
- creating campaign
- mock connecting account
- running dry-run
- viewing logs

Do not implement:
- SaaS billing
- Multiple workspaces UI
- V2 story replies
- AI replies
- Full design system complexity

Acceptance criteria:
- User can log in.
- User can mock connect an Instagram account locally.
- User can create draft campaign.
- User can activate campaign.
- User can simulate keyword matching.
- User can view leads/logs/messages.
- User can retry failed messages.
- Docker compose starts dashboard and backend.
```

---

# Phase 6 — Production Hardening for VPS

## Prompt

```txt
You are building Phase 6: production hardening and VPS deployment.

Objective:
Make the product safe and reliable to run on a company VPS with Docker, Nginx, HTTPS, backups, monitoring, and deployment documentation.

Use existing Phase 5 code.

Implement:

1. Production Docker Compose

Create:
docker-compose.prod.yml

Services:
- nginx
- backend
- dashboard
- worker
- beat
- postgres
- redis

Rules:
- postgres and redis must not expose public ports
- backend only accessible through nginx
- dashboard only accessible through nginx
- env_file .env.production
- persistent volumes for postgres, redis, letsencrypt/certs

2. Nginx

Create:
nginx/default.conf

Routes:
- / -> dashboard:3000
- /api/ -> backend:8000
- /auth/ -> backend:8000/auth/
- /meta/ -> backend:8000/meta/
- /instagram/ -> backend:8000/instagram/
- /campaigns/ -> backend:8000/campaigns/
- /leads/ -> backend:8000/leads/
- /messages/ -> backend:8000/messages/
- /logs/ -> backend:8000/logs/
- /stats/ -> backend:8000/stats/
- /webhooks/meta -> backend:8000/webhooks/meta
- /health -> backend:8000/health

Add:
- client body size limit
- proxy headers
- X-Forwarded-For
- X-Forwarded-Proto
- basic rate limiting for /webhooks/meta
- gzip optional

3. Environment examples

Create:
.env.production.example

Include:
- APP_ENV=production
- APP_BASE_URL=https://automation.yourdomain.com
- DATABASE_URL internal docker hostname
- REDIS_URL internal docker hostname
- JWT_SECRET
- APP_SECRET_KEY
- TOKEN_ENCRYPTION_KEY
- META_APP_ID
- META_APP_SECRET
- META_WEBHOOK_VERIFY_TOKEN
- META_GRAPH_API_VERSION
- SENTRY_DSN
- NEXT_PUBLIC_API_URL=https://automation.yourdomain.com

4. Backend production config

Ensure:
- CORS is restricted by env var ALLOWED_ORIGINS
- debug disabled in production
- docs can be disabled in production if configured
- trusted proxy headers handled if needed
- secure cookie settings if refresh token exists

5. Sentry

Add optional Sentry initialization:
- only if SENTRY_DSN is set
- capture backend exceptions
- add environment tag

6. Health endpoints

Update:
GET /health
Checks:
- app
- database
- redis

Add:
GET /webhooks/health
Returns:
- status
- last_event_received_at if available
- worker health if possible
- webhook status ok/unknown/alert

7. Backup scripts

Create:
scripts/backup_postgres.sh
scripts/restore_postgres.sh

Backup script:
- reads env
- pg_dump
- gzip
- optional gpg encryption if BACKUP_GPG_PASSPHRASE set
- writes to ./backups
- filename includes timestamp

Restore script:
- accepts backup filename
- confirms destructive action
- restores to postgres

Document off-server backup recommendation.

8. Deployment docs

Create:
docs/deployment-vps.md

Include:
- Ubuntu VPS preparation
- create non-root user
- SSH key login
- disable password auth
- UFW allow 22, 80, 443
- install Docker
- install Docker Compose plugin
- DNS A record setup
- clone repo
- create .env.production
- generate Fernet key
- start services
- run migrations
- create admin user
- configure Nginx/SSL
- register webhook URL in Meta Developer Console
- test webhook challenge
- test live campaign

9. SSL docs

Add Certbot or reverse proxy SSL instructions.
If not implementing automated certbot container, document exact commands.

10. Monitoring docs

Add:
docs/monitoring.md

Include:
- Sentry setup
- UptimeRobot / BetterStack health check
- Docker logs
- critical alerts:
  - backend down
  - worker down
  - redis down
  - postgres down
  - SSL expiring
  - token expiring
  - high failed message rate
  - no webhook events

11. Security checklist

Create:
docs/security-checklist.md

Include:
- no secrets committed
- tokens encrypted
- DB not publicly exposed
- Redis not publicly exposed
- webhook signature validation enabled
- HTTPS only
- rate limits enabled
- admin password strong
- backups tested
- Meta permissions minimal

12. Tests

Add/adjust tests:
- health fails if DB unavailable mocked
- redis health check mocked
- production CORS uses allowed origins
- webhook signature still required in production
- no plaintext token regression test remains

Do not implement:
- V2 features
- billing
- SaaS tenant isolation

Acceptance criteria:
- docker-compose.prod.yml is complete.
- Nginx routes are documented and consistent.
- Production env example is complete.
- Backup and restore scripts exist.
- Deployment guide is usable by an engineer.
- Health endpoints include DB and Redis.
- Security checklist exists.
```

---

# Phase 7 — V2 Expansion After MVP Stability

## Prompt

```txt
You are building Phase 7 V2 features.

Important:
Only start this after the MVP is working in production or staging.

Objective:
Add expansion features without breaking the core comment-to-private-reply MVP.

Before coding:
1. Inspect current codebase.
2. Identify which V2 feature is being requested.
3. Implement only one V2 feature per task.
4. Add tests.
5. Preserve all existing MVP behavior.

Allowed V2 features:
- multi-step conversations after user replies
- DM keyword automations
- story reply automations
- any-post keyword automation
- A/B message variants
- lead tags and segmentation
- CRM webhook integrations
- multiple team members
- roles: admin, campaign_manager, viewer
- analytics charts
- opt-out tracking
- data deletion request flow
- multi-workspace/multi-client support

Global V2 rules:
- Never send unsolicited DMs.
- Respect Meta messaging windows.
- Opted-out users must never be messaged.
- Keep idempotency constraints.
- Add migrations for schema changes.
- Add dashboard controls only after backend behavior exists.
- Add audit logs for every new automation action.

For each V2 feature, output:
- feature implemented
- data model changes
- endpoints added
- dashboard pages changed
- tests added
- policy/compliance considerations
- manual verification steps
```

---

# Recommended Use

Use the prompts in this order:

```txt
Global rules + Phase 0
Review output
Run tests
Commit

Global rules + Phase 1
Review output
Run tests
Commit

Global rules + Phase 2
Review output
Run tests
Commit
...
```

Do not give the coding agent multiple phases at once.
