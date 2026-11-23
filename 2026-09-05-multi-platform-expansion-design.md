# ManyOsirisChat — Multi-Platform Expansion Design

**Status:** Draft — pending approval
**Author:** Claude (with Youssef)
**Date:** 2026-09-05

## 1. Goal

Expand ManyOsirisChat from Instagram-only to a multi-platform product per client:
one workspace (client) can connect and manage **Instagram**, **WhatsApp**, and
**Facebook Pages**, each clearly labeled and filterable in the dashboard, with the
same AI conversation-continuation engine powering all three.

**Hard constraint:** the existing Instagram implementation must not be modified.
Every table, model, service, route, and migration currently touching
`instagram_accounts` stays exactly as-is. All new capability is additive.

## 2. What the current codebase actually looks like (investigated, not assumed)

- `Workspace` is the tenant/client concept. This is the correct anchor for
  "one client, many platforms" — no change needed here.
- `InstagramAccount` is a single wide table: connection/token status, campaign
  AI settings, and cold-DM AI settings all live on it. It is referenced by
  `MetaToken`, `Lead`, `Conversation`, `Campaign`, and `Comment` via a
  non-nullable `instagram_account_id` FK, and directly imported in ~22 backend
  files and 8 dashboard files.
- Cold-DM AI is already shipped (migration `0010_cold_dm_ai.py`): `Lead.lead_source`
  (`campaign` | `cold_dm`) and `InstagramAccount.ai_cold_dm_enabled` exist today.
  This is the closest existing precedent for the WhatsApp phase — WhatsApp is
  cold-DM-shaped by nature (no comment triggers, just inbound DM → AI reply).
- Webhooks are a single shared endpoint (`POST /webhooks/meta`) → `store_webhook_event`
  → Celery task `process_webhook_event`, which unconditionally runs three
  Instagram-specific parsers (`parse_instagram_comment_events`,
  `parse_instagram_postback_events`, `parse_instagram_message_events`) against
  every payload, then resolves the account via `InstagramAccount.ig_user_id`.
  There is currently no branch on `payload["object"]` — there's never needed
  to be one.
- `Campaign` and `Comment` are Instagram-specific by design (media targeting,
  comment triggers) — Facebook's comment-to-DM flow will need its own
  equivalents, not shared tables, since the underlying concepts (page feed
  posts vs. IG media, no `is_user_follow_business` equivalent) genuinely differ.
- `ai_service.py` / `conversation_service.py` (the GPT-4o mini conversation layer)
  are the reusable core — they operate on `Conversation` + `Lead` rows and don't
  inherently know about Instagram's Graph API specifics, which is what makes
  cross-platform reuse realistic.

## 3. Foundation approach (confirmed: Option C)

Add new, fully separate tables for each new platform — modeled after
`InstagramAccount`'s shape but independent:

- `whatsapp_accounts` (Phase 2)
- `facebook_pages` (Phase 3)

`Lead` and `Conversation` gain:
- A `platform` enum column: `'instagram' | 'whatsapp' | 'facebook'`
  (default `'instagram'`, backfilled for all existing rows — zero behavior change).
- New nullable FKs: `whatsapp_account_id`, `facebook_page_id`.
- `instagram_account_id` remains as-is (already nullable-safe since it's just
  unused/NULL on non-IG rows going forward — no change to its column definition
  or existing NOT NULL constraint is required if we only ever populate exactly
  one of the three FKs per row and leave `instagram_account_id` NOT NULL only
  where it already is, i.e. this stays untouched for existing rows).
- A DB-level CHECK constraint ensuring exactly one of the three account FKs is
  set, matching `platform`.

This is deliberately over-normalized in the short term (three parallel FK
columns instead of one polymorphic FK) so that:
- Every existing IG query (`WHERE instagram_account_id = ...`) keeps working
  with zero changes.
- A future consolidation into a single `social_accounts` table + one
  `social_account_id` FK is a **mechanical backfill migration**
  (`social_account_id = COALESCE(instagram_account_id, whatsapp_account_id, facebook_page_id)`)
  rather than a rewrite — explicitly not committed to now, just not foreclosed.

### Webhook dispatch

`process_webhook_event` gets one new early branch on `payload.get("object")`:
`"instagram"` → existing parsers, completely unchanged code path.
`"whatsapp_business_account"` → new WhatsApp parser (Phase 2).
`"page"` → new Facebook parser (Phase 3).
Unknown/missing `object` → logged and skipped, same as today's fallback.

This branch is the only change to `tasks.py` needed to keep IG behavior
byte-for-byte identical while making room for new platforms.

### Dashboard

- A `platform` filter (tabs or dropdown) on Leads, Conversations, and the
  Accounts page — reads the new `platform` column, defaults to showing all.
- Platform badges (icon + label) reused across list views, same visual pattern
  as the existing `lead_source` badge.
- Account connection page shows three connect buttons (Instagram / WhatsApp /
  Facebook) rather than one — each routes to its own OAuth/setup flow.

## 4. Phases

### Phase 1 — Foundation (no user-facing platform yet)
**Scope:**
- Migration: `platform` enum + nullable FKs on `Lead`/`Conversation`, CHECK
  constraint, backfill existing rows to `platform = 'instagram'`.
- Webhook dispatcher branch on `payload["object"]` (routes to existing IG
  parsers unchanged; unknown objects still skipped/logged as today).
- Dashboard: platform column/badge added to Leads and Conversations tables
  (will only ever show "Instagram" until Phase 2 ships, but proves the UI
  pattern and avoids a rushed retrofit later).
- No new external integrations yet — this phase is pure groundwork.

**Done when:** all existing IG tests still pass unmodified, existing dashboard
views look identical except for a new (currently redundant) platform badge.

### Phase 2 — WhatsApp Cloud API (reactive only)
**Scope, confirmed:**
- Direct Meta WhatsApp Cloud API (own Meta app product + App Review, own phone
  number registration) — not a BSP like Twilio/360dialog.
- Reactive only: bot replies when a user messages first, within the 24-hour
  customer service window. No outbound template-based broadcasts in this phase.
- New `whatsapp_accounts` table: phone number ID, display name, status, and
  the same AI-settings shape as `InstagramAccount` (`ai_enabled`,
  `ai_business_profile`, `ai_tone_instructions`, `ai_daily_message_cap`,
  `ai_handoff_after_turns`, budget tracking) — WhatsApp has no campaign
  concept, so this is effectively "cold-DM AI settings" and nothing else.
- New WhatsApp webhook parser (mirrors `parse_instagram_message_events`'
  shape/spirit, adapted to the Cloud API's message webhook format).
- New `whatsapp_service.py` / messaging client (send message via Cloud API,
  separate from `integrations/meta/messaging.py`).
- Reuses `ai_service.py`/`conversation_service.py` as-is where possible —
  `Conversation` rows get `platform='whatsapp'`, `whatsapp_account_id` set,
  `instagram_account_id`/`campaign_id` left NULL.
- Dashboard: WhatsApp connect flow, account-level AI settings form (same shape
  as the existing Instagram account settings UI), Conversations/Leads tabs now
  show real WhatsApp rows alongside Instagram.

**Explicit non-goals for Phase 2:** template-based outbound campaigns,
multi-number-per-workspace UI polish (single number per workspace is enough
to start), anything beyond reactive AI conversation.

### Phase 3 — Facebook Pages (comment-to-DM + AI)
**Scope:**
- Facebook Login for Business OAuth (distinct from Instagram Login) — new
  `routes_facebook.py`, new `oauth.py` counterpart.
- New `facebook_pages` table (parallel to `InstagramAccount`).
- New `facebook_campaigns`, `facebook_comments` tables — **not** shared with
  `Campaign`/`Comment`, since post/media targeting and comment-webhook shape
  differ enough (and because IG's `Campaign`/`Comment` tables must stay untouched).
- New comment/postback/message parsers for `payload["object"] == "page"`.
- Follow-gate equivalent redesigned for Facebook's actual consent mechanics
  (no `is_user_follow_business` field on FB Pages — needs its own research
  spike at the start of this phase to confirm what FB's Graph API actually
  offers here before design is finalized).
- Reuses the AI conversation layer the same way Phase 2 does.
- Dashboard: Facebook connect flow, campaign builder (adapted from the IG
  campaign form, not shared component-for-component if the underlying data
  shape diverges too much), platform badges now show all three platforms live.

**Explicit dependency:** Phase 3's follow-gate/consent design needs a short
research spike (confirm exact Graph API fields available for FB Page comment
consent) before the schema for `facebook_campaigns` can be finalized — flagged
here so it isn't discovered mid-implementation.

## 5. Cross-cutting principles carried through all phases

- **No shared mutation of IG tables, ever.** Any temptation to "just add one
  more nullable column to `instagram_accounts` for consistency" should be
  resisted — new platforms get new tables, full stop.
- **`platform` is the single source of truth** for dashboard filtering —
  every new list/detail view added in Phases 2–3 must key off it, not off
  which FK happens to be non-null (even though that's implied by the CHECK
  constraint).
- **AI settings shape stays consistent** across platforms (business profile,
  tone instructions, daily cap, handoff-after-turns) even though the
  underlying account tables are separate — this is what makes "same AI
  responding as Instagram DMs" true in practice for WhatsApp and Facebook.
- **Investigate-before-code still applies per phase.** Before Phase 2 or 3
  implementation starts, re-verify the current repo state (migrations may
  have moved on) rather than assuming this spec's file/line references are
  still exactly accurate.

## 6. Open questions to resolve before Phase 3 implementation (not blocking Phase 1/2)

- Exact Facebook Graph API consent/follow-equivalent mechanics.
- Whether Facebook campaigns need their own `delivery_mode`/`cooldown_hours`
  concepts identical to Instagram's, or whether FB's rate-limit norms differ.
- Single vs. multi-number-per-workspace for WhatsApp, longer-term (Phase 2
  ships single-number only).
