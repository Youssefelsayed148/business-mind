# WhatsApp Outreach — Implementation Plan

Depends on: migration 0018 merged and applied.
Direct Meta WhatsApp Cloud API only (no BSP). Official Embedded Signup remains the
only way numbers are connected.

## Principles
1. One choke point. All business-initiated sends go through
   `outreach_service.check_can_send(contact, template, account)`. No other code
   path may send a template.
2. Consent is explicit. Only these set marketing_consent='opted_in': public opt-in
   form, click-to-WhatsApp referral, inbound opt-in keyword, or a dashboard import
   where the user ticks an attestation. Every change writes a consent_events row.
3. Opt-out always wins, is instant, and applies across all campaigns.
4. Fail closed. If account health is unknown, quality is RED, or the account is
   paused, sends stop.
5. Workspace-scoped everywhere using the existing workspace dependencies in authz.py.

## Phase 0 — Read-only investigation (report before coding)
Read: tasks.py WhatsApp path (_process_whatsapp_message_events,
_dispatch_whatsapp_ai_turn, process_whatsapp_ai_conversation_turn), the webhook
dispatcher, whatsapp_webhooks.py, whatsapp_client.py, routes_whatsapp.py, authz.py,
beat_schedule.py, rate_limit_service.py, the existing template_service.py (name
clash: new code uses whatsapp_template_service.py), tests for WhatsApp.
Report: where each hook point is, and what the current Graph API version setting
means (META_GRAPH_API_VERSION is v21.0 — check Meta's current supported versions
and flag it, do not bump silently).

## Phase 1 — Webhooks
Extend whatsapp_webhooks.py with parsers (pure functions + tests):
- value.statuses[]: sent/delivered/read/failed with error codes -> update
  messages.status/delivered_at/read_at and campaign recipient + counters.
  Map known codes: 131026 (undeliverable), 131049 (marketing frequency cap,
  not retryable, do not hammer), 131048/130429 (rate limits, retry with backoff),
  132000-series (template param/paused issues).
- messages[].type == 'interactive' / 'button': parse button replies; treat quick-reply
  payloads "STOP"/"UNSUBSCRIBE" as opt-out.
- messages[].referral (click-to-WhatsApp): set free_entry_point_expires_at = now+72h,
  and consent_source='click_to_whatsapp' only if the ad flow collected opt-in
  (make this a per-account setting, default off).
- Template/health events: message_template_status_update,
  message_template_quality_update, phone_number_quality_update, account_update ->
  update whatsapp_templates and whatsapp_accounts.
- Opt-out keywords: configurable list (English + Arabic: stop, unsubscribe, cancel,
  and Arabic equivalents of stop/unsubscribe). Exact-match on normalized short
  messages only, to avoid false opt-outs from long sentences.
- Opt-in keywords (e.g. "START") set opted_in with source 'inbound_keyword'.
- On every inbound message update contacts.last_inbound_at; create the contact
  row if missing (consent stays 'unknown').
- Deduplicate through the existing processed-webhook-event mechanism.

## Phase 2 — Cloud API client (WhatsappClient + new WhatsappManagementClient)
- send_template_message(access_token, phone_number_id, to, template_name, language,
  components) -> MetaMessageResult.
- Templates: create, list, delete via /{waba_id}/message_templates.
- Phone health: GET /{phone_number_id}?fields=quality_rating,messaging_limit_tier,
  verified_name,status (field names: verify against current Meta docs).
- Keep the META_MOCK_PRIVATE_REPLIES behaviour so tests stay hermetic.

## Phase 3 — Services
- consent_service: grant(), revoke(), is_marketing_allowed(), always writes
  consent_events; import_contacts(csv, attestation_text, actor) rejects the import
  unless an attestation string is supplied, normalizes numbers to E.164, dedupes.
- whatsapp_template_service: create draft -> submit to Meta -> sync status;
  validate name format, category, variable count/examples.
- window helper: in_service_window(contact) -> last_inbound_at within 24h;
  in_free_entry_window(contact).
- outreach_service.check_can_send returns (allowed, reason) and checks, in order:
  account connected -> not outreach_paused -> quality not RED -> contact not
  opted_out -> marketing_consent=='opted_in' (for marketing templates; utility
  templates for an existing transaction may be allowed with consent 'unknown' only if
  the workspace attests a transactional relationship — default off) ->
  template approved and not paused -> daily tier limit not exhausted
  (count distinct recipients in rolling 24h vs messaging_limit_tier) -> not already
  sent in this campaign.
  Every refusal is recorded as a skipped_* recipient status with the reason.
- AI layer: must not send outside the window and must stop for opted_out contacts.
  Add a guard in the WhatsApp AI turn only (do NOT touch process_ai_conversation_turn).

## Phase 4 — Celery
- start_whatsapp_campaign(campaign_id): freeze the audience (consented contacts),
  create recipient rows, set total_recipients, status=running.
- send_whatsapp_campaign_message(recipient_id): re-run check_can_send immediately
  before the API call, use a Redis token bucket at throttle_per_minute, retry
  retryable errors with exponential backoff, never retry 131049.
- Beat: every 60 min sync template statuses; every 30 min refresh phone health
  and auto-pause outreach (outreach_paused=true, reason recorded, campaigns ->
  paused) when quality is RED or the tier dropped.
- Campaign completion rollup when no queued recipients remain.

## Phase 5 — API routes (routes_whatsapp_outreach.py, workspace-scoped, role-checked)
- Contacts: list/filter, detail with consent history, CSV import (attestation required),
  manual consent grant/revoke.
- Public opt-in: POST /public/whatsapp/opt-in/{signed_token}; token signs
  workspace+account, rate limited, records IP/URL as evidence, returns generic
  success (no enumeration).
- Templates: CRUD, submit, sync, preview.
- Campaigns: create/edit draft, dry-run (returns eligible vs skipped counts with
  reasons), start, pause, resume, cancel, stats.
- Account health endpoint.

## Phase 6 — Dashboard (Next.js)
Pages: WhatsApp > Contacts, Templates, Campaigns, Health. Required UX:
- Import dialog with a mandatory attestation checkbox and plain-language text.
- Campaign wizard: template -> audience -> variable mapping -> dry-run summary -> start.
- Visible banner when outreach is paused, with the reason.
- Template editor and "send test to my own number" flow (this is the flow recorded
  for Meta App Review).
- Consent source shown on every contact.

## Phase 7 — Tests
Unit tests per parser/service; the invariant test: no code path other than
outreach_service-approved sends can call send_template_message; opted_out contact
never receives a send; paused account sends nothing; frequency-cap error is not
retried; cross-workspace access returns 404/403.

## Out of scope
Instagram/Facebook changes, BSP integrations, scraping or list purchasing, any
unofficial WhatsApp library, billing/subscription work.

## Manual Meta-side steps (the agent cannot do these)
1. Subscribe the app's WhatsApp webhook fields: messages,
   message_template_status_update, message_template_quality_update,
   phone_number_quality_update, account_update.
2. Create the Embedded Signup configuration, set WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID.
3. After Phase 6 works, record the two App Review videos and request advanced
   access for whatsapp_business_messaging and whatsapp_business_management.
4. Before production, rotate the leaked Popeye token and remove that file from git.