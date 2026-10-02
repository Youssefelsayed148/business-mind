# WhatsApp Outreach — Migration Plan (0018)

## Goal
Add the schema for compliant, opt-in WhatsApp outreach: consent, templates,
campaigns, delivery status, and account health. Purely additive.

## Ground truth (verify before writing anything)
- Alembic head is `0017_workspace_membership` (down_revision `0015_conv_cold_dm_uniq`;
  there is no 0016 file). New revision `0018_whatsapp_outreach` must chain from
  `0017_workspace_membership`. Confirm with `alembic heads` and `alembic history`.
- Existing: `whatsapp_accounts`, `whatsapp_tokens`, `leads`, `conversations`,
  `messages`, `automation_logs`, `workspaces`.
- Messages is shared with Instagram/Facebook. Do not change existing columns.

## Design decision: consent is NOT inferred from inbound messages
A user messaging us permits replies inside the 24h window. It is not marketing
opt-in. So consent is tracked separately from "has contacted us".

## New tables
1. whatsapp_contacts
   - id uuid pk; workspace_id fk workspaces; whatsapp_account_id fk whatsapp_accounts
   - wa_id varchar(32) (digits only, E.164 without '+'); display_name; lead_id fk leads null
   - marketing_consent varchar(20): 'unknown' | 'opted_in' | 'opted_out' (default 'unknown')
   - consent_source varchar(40) null: web_form | click_to_whatsapp | inbound_keyword |
     in_store | imported_attested | manual
   - consent_at timestamptz null; opted_out_at timestamptz null
   - last_inbound_at timestamptz null (24h window anchor)
   - free_entry_point_expires_at timestamptz null (72h CTWA window)
   - created_at, updated_at
   - UNIQUE (whatsapp_account_id, wa_id); INDEX (workspace_id, marketing_consent)
   - CHECK marketing_consent in the three values
2. whatsapp_consent_events (append-only audit log)
   - id; contact_id fk; workspace_id fk; event_type: opt_in | opt_out | import | revoke
   - source varchar(40); evidence jsonb (form URL, IP, attestation text, file name, keyword)
   - actor_user_id fk users null; created_at
   - INDEX (contact_id, created_at)
3. whatsapp_templates
   - id; workspace_id; whatsapp_account_id; meta_template_id varchar null
   - name varchar(512); language varchar(16); category: marketing | utility | authentication
   - status: draft | pending | approved | rejected | paused | disabled
   - rejection_reason text null; components jsonb; quality_score varchar(20) null
   - last_synced_at; created_at; updated_at
   - UNIQUE (whatsapp_account_id, name, language)
4. whatsapp_campaigns
   - id; workspace_id; whatsapp_account_id; template_id fk whatsapp_templates
   - name; status: draft | scheduled | running | paused | completed | cancelled | failed
   - scheduled_at null; throttle_per_minute int default 30
   - variable_mapping jsonb (template placeholder -> contact field / literal)
   - total_recipients, sent_count, delivered_count, read_count, failed_count,
     skipped_count (int default 0); created_by fk users; created_at; updated_at
5. whatsapp_campaign_recipients
   - id; campaign_id fk (ON DELETE CASCADE); contact_id fk
   - status: queued | sent | delivered | read | failed | skipped_no_consent |
     skipped_opted_out | skipped_not_eligible
   - message_id fk messages null; provider_message_id null; error_code null; error_message null
   - sent_at null; UNIQUE (campaign_id, contact_id); INDEX (campaign_id, status)

## Altered tables (additive only)
- whatsapp_accounts: quality_rating varchar(20) null (GREEN|YELLOW|RED),
  messaging_limit_tier varchar(30) null, outreach_paused bool default false,
  outreach_paused_reason text null, health_checked_at timestamptz null
- messages: whatsapp_campaign_id uuid fk null, whatsapp_template_id uuid fk null,
  delivered_at timestamptz null, read_at timestamptz null
  (statuses sent/delivered/read/failed reuse the existing status column)
- automation_logs: no change.

## Backfill
- For every lead with platform='whatsapp', insert a whatsapp_contacts row:
  wa_id = lead.ig_user_id (this is where the WA ID is stored), marketing_consent
  = 'unknown', last_inbound_at = lead.last_seen_at, lead_id = lead.id.
  Idempotent (ON CONFLICT DO NOTHING). Do NOT mark anyone opted_in.

## Rules
- Additive only: never modify instagram_accounts or existing columns' types.
- Order: create tables -> add columns -> backfill -> constraints/indexes.
- Full downgrade that drops everything in reverse order.
- Add SQLAlchemy models for each new table and register them in models/__init__.py.
- Verify against information_schema, not the model files.

## Acceptance
- alembic upgrade head, downgrade -1, upgrade head all succeed on a clean DB
  and on a production snapshot.
- Backfill count equals the number of WhatsApp leads; zero contacts opted_in.
- Constraints reject: duplicate (account, wa_id), invalid consent value.
- Existing test baseline unchanged (compare failure lists, not counts).