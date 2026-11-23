# Claude Code prompt — Phase 3: Facebook Pages (comment-to-DM + AI)

Read `docs/specs/2026-09-05-multi-platform-expansion-design.md` first — especially
Section 4 Phase 3 and Section 5 (cross-cutting principles). Only implement Phase 3.

**Phase 1 and Phase 2 are merged.** Current migration head is
`0012_whatsapp_accounts` (`backend/alembic/versions/`); your new migration is
`0013_facebook_pages.py`, `down_revision = "0012_whatsapp_accounts"`. The
current backend test baseline is **23 pre-existing failures, unrelated to the
multi-platform work** (same infra/test-isolation gaps noted in the Phase 1/2
prompts — no Celery eager-mode config anywhere in the repo). Re-confirm this
number before you start (`pytest tests/ -q` against real Postgres+Redis) since
it's a moving target — compare your before/after failure **list**, not the
raw count.

This file was rewritten after a full re-investigation of the actual
post-Phase-2 codebase (exact file/line citations below) plus external
research into current Facebook Graph API mechanics. Two things could not be
fully resolved by research alone and are flagged as open in the research
spike section — resolve those first, they change the schema.

## Hard constraints
- Do NOT modify `instagram_accounts`, `campaigns`, `comments`, or any existing
  Instagram service/route/worker logic. This has held through Phases 1–2; it
  holds here.
- Do NOT modify `whatsapp_accounts`, `whatsapp_tokens`, `_dispatch_whatsapp_ai_turn`,
  `_process_whatsapp_message_events`, or `process_whatsapp_ai_conversation_turn`
  (all in `backend/app/workers/tasks.py`) — these are Phase 2's, and the
  "own task per platform" pattern Phase 2 established (see Section 4 below)
  means Facebook needs its own copies, not edits to WhatsApp's.
- The one sanctioned exception: `conversation_service.get_or_create_conversation`
  needs one more additive keyword parameter, exactly mirroring how Phase 2
  added `platform`/`whatsapp_account_id` to it. Nothing else in
  `conversation_service.py` or `ai_service.py` needs to change — see Section 4,
  both already work for Facebook with zero edits.
- Facebook gets its own tables (`facebook_pages`, `facebook_campaigns`,
  `facebook_comments`, plus a token table and a keywords table — see Section 1) —
  not shared with Instagram's `Campaign`/`Comment`/`CampaignKeyword`/`MetaToken`.
  Confirmed necessary, not just cautious: `Campaign` has no `platform` column
  and `campaign_matcher.find_matching_campaigns()` takes a hard-typed
  `instagram_account_id: UUID` parameter and filters
  `Campaign.instagram_account_id == instagram_account_id`
  (`backend/app/services/campaign_matcher.py:45-52`) — there's no generic seam
  to extend there, only a pattern to mirror in a new file.

## Required first step: research spike (resolve before finalizing schema)

Two things need a real answer before `facebook_campaigns`' shape can be
finalized. Preliminary findings below are from public Meta documentation as
of this writing — verify against current docs before committing, since Meta
changes these APIs without much notice.

**1. Is there a Facebook Page equivalent of `is_user_follow_business`?**
Preliminary finding: **likely no.** `is_user_follow_business`
(`backend/app/integrations/meta/messaging.py:418-479`,
`MetaMessagingClient.get_is_user_follow_business`) is an Instagram Platform
User Profile API field, gated on the user having sent a message/tapped a
postback first. Public Facebook Graph API documentation does not surface an
equivalent per-commenter "does this person follow the Page" field — Meta has
progressively locked down exposing a Page's follower graph per-user for
privacy reasons. **Recommendation: Facebook campaigns in this phase support
only `delivery_mode = "instant"`** (immediate private reply on keyword match,
no follow-gate) — **do not build the `follow_prompt`/`FOLLOW_CHECK` postback
flow for Facebook.** This means `facebook_campaigns` does not need
`follow_prompt_title`/`follow_prompt_description`/`follow_prompt_profile_url`
columns, and there's no Facebook equivalent of `check_follow_and_deliver`
(`backend/app/workers/tasks.py:1348-1523`) or `send_follow_prompt_card`
(`backend/app/workers/tasks.py:1180-1330`) to write. If your research finds a
real mechanism Meta does expose for this, report it before adding those
columns — don't add them speculatively.

**2. Does Facebook's "one private reply per comment" constraint match
Instagram's subcode-2534014 behavior?** Preliminary finding: **yes, same
underlying mechanism.** Facebook's Graph API `private_replies` edge
documentation states a comment "may only be replied to once," and separately
confirms private replies must be sent within a time window of the comment (7
days, per current docs — verify this, Instagram's equivalent window isn't
documented as a hard limit anywhere in this codebase, so don't assume they
match). This is the same Messenger Platform infrastructure Instagram
messaging is built on. Practically: `_send_private_reply_impl`'s pattern
(`backend/app/workers/tasks.py:955-959` — first reply via
`recipient.comment_id`, once a user takes any action the door opens to
`recipient.id` for the rest of the 24h window) should carry over directly to
Facebook. Build the Facebook client with the same two-method split
(`send_private_reply` / `send_direct_message` equivalents) as
`MetaMessagingClient`.

**3. What OAuth product/flow shape does Facebook Page connection actually
use?** This repo currently has two different shapes and Facebook Pages could
plausibly go either way — confirm which before writing `routes_facebook.py`:
- Instagram (`backend/app/integrations/meta/oauth.py`,
  `backend/app/api/routes_meta.py:52-107`): "Instagram API with Instagram
  Login" — a classic server-redirect OAuth flow (`build_oauth_url` →
  `graph.instagram.com`/`api.instagram.com`, GET callback with
  `code`/`state` query params, CSRF state stored in Redis under
  `oauth_state:{state}`, deleted on use).
- WhatsApp (`backend/app/api/routes_whatsapp.py`, Phase 2): "WhatsApp
  Embedded Signup," a specific product under **Facebook Login for Business**
  — client-side `FB.login()` popup with a `config_id` (no server redirect
  URL at all), a POST JSON callback carrying an authorization `code`, CSRF
  state stored under `whatsapp_oauth_state:{state}`.

The design doc and this prompt both name the Facebook Page flow **"Facebook
Login for Business"** — the same product family name as WhatsApp's Embedded
Signup, not plain "Facebook Login." That naming is a signal (not proof) that
Facebook Page connection likely uses the **same config_id/`FB.login()` popup
shape as WhatsApp**, just with different permission scopes and a different
response shape (Facebook Login for Business typically returns granted Pages
via a `GET /me/accounts` call using the resulting user token — each Page in
that list carries its own Page Access Token directly, no per-Page exchange
needed — rather than a WhatsApp-style `postMessage` payload). If research
confirms this, mirror `routes_whatsapp.py`'s structure
(`WhatsappConnect.tsx`'s `FB.login()` + config_id pattern, `_redis()`
singleton, `secrets.token_urlsafe(24)` state, POST callback) rather than
`routes_meta.py`'s redirect pattern — but a Page connect flow additionally
needs to let the user pick which Page(s) to connect from the `/me/accounts`
list, which WhatsApp's single-number flow didn't need. Report your finding
before writing the OAuth code either way.

## Scope for this session (once the spike above is resolved)

### 1. Data model

**`leads.facebook_page_id` and `conversations.facebook_page_id` already
exist** (added in Phase 1, still bare nullable UUID columns with no FK
target) **and the CHECK constraints already reference `platform='facebook'`**
(`ck_leads_platform_account_fk` / `ck_conversations_platform_account_fk` —
see `backend/app/models/lead.py:20-28` and
`backend/app/models/conversation.py:25-33`). Your migration only needs to add
the FK constraints now that `facebook_pages` will exist, exactly mirroring
`0012_whatsapp_accounts.py`'s pattern for `whatsapp_account_id`: give the
model-level `ForeignKey(...)` an explicit `name=` matching the migration's
constraint name (Phase 2 hit a duplicate-FK bug from skipping this — see
`backend/app/models/lead.py`'s `whatsapp_account_id` column comment for why),
and make the migration's FK-creation idempotent by existence-check (`0012`'s
`_create_fk_if_missing` helper is a direct template — copy it).

**New `facebook_pages` table** — model this on `InstagramAccount`'s **full**
shape (`backend/app/models/instagram_account.py`), not `WhatsappAccount`'s
trimmed one. Reasoning: WhatsApp dropped `ai_cold_dm_enabled` and all
campaign fields because it's reactive-only with no campaign concept; Facebook
Pages *do* have a campaign/comment-trigger concept (this phase's whole
point), so `facebook_pages` needs the same shape Instagram has: `id`,
`workspace_id`, `page_id`, `page_name`, `status`, `business_vertical`,
`ai_enabled`, `ai_cold_dm_enabled` (for direct Page-inbox messages outside
any campaign, mirroring Instagram's cold-DM precedent), `ai_business_profile`,
`ai_tone_instructions`, `ai_daily_message_cap`, `ai_handoff_after_turns`,
`ai_messages_sent_today`, `ai_budget_reset_at`.

**New `facebook_tokens` table** — do not extend `MetaToken`
(`backend/app/models/meta_token.py`): `instagram_account_id` there is `NOT
NULL` with an FK strictly to `instagram_accounts`, same blocker Phase 2 hit.
Mirror `backend/app/models/whatsapp_token.py` exactly, with
`facebook_page_id` in place of `whatsapp_account_id`.

**New `facebook_campaigns` table** — mirrors `Campaign`'s shape
(`backend/app/models/campaign.py`) but scoped to Facebook's post/comment
model and **without** the follow-prompt columns per the research spike
finding above (no `delivery_mode` beyond `"instant"`, no
`follow_prompt_title`/`follow_prompt_description`/`follow_prompt_profile_url`).
Keep: `facebook_page_id` FK, `name`, a post/media reference (Facebook calls
it a `post_id`, not IG's `media_id` — same concept, different field name,
confirmed by the webhook payload shape below), `target_scope`, `match_type`,
`message_template`, `cooldown_hours`, `status`, `comment_reply_enabled`,
`comment_reply_text`, `ai_enabled`, `ai_handoff_after_turns`,
`total_triggers`/`successful_sends`/`failed_sends`. Needs its own
`facebook_campaign_keywords` table too (mirrors `CampaignKeyword`,
`backend/app/models/campaign_keyword.py`) — `Campaign`/`CampaignKeyword`
aren't reusable via a nullable FK the way `leads`/`conversations` are,
because `Campaign.instagram_account_id` is `NOT NULL` and campaign matching
is looked up by that column specifically (see Section 4).

**New `facebook_comments` table** — mirrors `Comment`
(`backend/app/models/comment.py`, currently `instagram_account_id` NOT NULL,
zero platform awareness) scoped to Facebook's webhook comment shape:
`facebook_page_id` FK, `comment_id` (unique), `post_id`, `from_id`,
`from_name`, `message`, `normalized_text`, `received_at`, `created_at`. Also
needs a `verb` distinction Instagram's parser doesn't have to handle — see
Section 2.

**`messages.facebook_campaign_id` and `messages.facebook_comment_id`** —
this one is easy to miss because it's not mentioned anywhere in the design
doc: `Message.campaign_id` and `Message.comment_id`
(`backend/app/models/message.py:23-31`) are FK'd strictly to `campaigns.id`
and `comments.id` — the same lock that makes `Campaign`/`Comment`
unreusable, but on the table every send actually gets recorded in
(`_dispatch_ai_turn`/`process_ai_conversation_turn` both create `Message`
rows). A Facebook campaign-triggered reply cannot set `campaign_id` to a
`facebook_campaigns.id` value. Add `facebook_campaign_id` and
`facebook_comment_id` as new nullable FK columns on `messages` (simpler than
the `leads`/`conversations` precedent — these two are already nullable on
`Message`, so no NOT NULL relaxation is needed, just new additive columns).
Also add a second unique constraint,
`uq_message_facebook_campaign_comment_type (facebook_campaign_id,
facebook_comment_id, message_type)`, alongside the existing
`uq_message_campaign_comment_type` — same NULL-distinctness reasoning as
`uq_lead_workspace_whatsapp_user` in Phase 2: this is what actually enforces
"one private reply per comment" for Facebook rows, since the existing
constraint never sees non-NULL values in its own two columns for Facebook
messages. Cold-DM-style Facebook messages (from `ai_cold_dm_enabled`, no
originating campaign) leave both new columns NULL, same as Instagram's
cold-DM messages do today.

**`automation_logs.facebook_page_id`** — does not exist yet (Phase 2 added
`whatsapp_account_id` to this table; there is no `facebook_page_id` column).
Add it the same way, nullable + FK to `facebook_pages.id`, and add a
`facebook_page_id` parameter to `log_action()`
(`backend/app/services/log_service.py`) alongside the existing
`instagram_account_id`/`whatsapp_account_id` ones.

**Migration file**: `0013_facebook_pages.py`, `down_revision =
"0012_whatsapp_accounts"`. Copy `0012`'s idempotency helpers wholesale
(`_table_names`, `_columns`, `_add_column_if_missing`, `_constraint_names`,
`_create_fk_if_missing`, etc.) — same fresh-DB-vs-incremental-DB gotcha
applies here (`0001_initial.py` creates tables from live models via
`Base.metadata.create_all()`, so a fresh DB will already have everything your
migration tries to add).

### 2. Meta integration

- `app/integrations/meta/facebook_oauth.py` — per the research spike's item
  3. Whichever shape you confirm, mirror the corresponding existing file
  structurally (`oauth.py` or `whatsapp_oauth.py`).
- `app/integrations/meta/facebook_webhooks.py` — new parser(s) for
  `payload["object"] == "page"`. Facebook's comment webhook shape (confirmed
  via Meta's current docs) is structurally close to Instagram's:
  `field: "feed"` (not IG's `field: "mentions"`), `value.item: "comment"`,
  `value.comment_id`, `value.post_id` (not IG's `media_id`), `value.from`,
  `value.message`, and **`value.verb`** (`"add"` / `"edited"` / `"remove"`) —
  a field Instagram's `parse_instagram_comment_events`
  (`backend/app/integrations/meta/webhooks.py:63-131`) doesn't have to check.
  **Your Facebook parser must filter to `verb == "add"` only** — Facebook
  sends webhook notifications for comment edits and deletions too, which
  Instagram's parser was never written to defend against because it doesn't
  need to. Mirror `parse_instagram_comment_events`'s shape/spirit otherwise.
  Also need a Messenger-message/postback parser for the private-reply
  follow-up path (mirrors `parse_instagram_postback_events`/
  `parse_instagram_message_events`, same file or a sibling) — the underlying
  Messenger Platform event shape is shared between IG and FB, so this should
  translate closely once you're past the `field`/`post_id` naming differences.
- `app/integrations/meta/facebook_client.py` — mirror `MetaMessagingClient`'s
  two-send-method split (`send_private_reply` via `recipient.comment_id`,
  `send_direct_message` via `recipient.id`) per the research spike's item 2.
  No `send_follow_prompt_card` equivalent needed (item 1's finding).

### 3. Webhook dispatch

Extend `process_webhook_event`'s dispatcher branch
(`backend/app/workers/tasks.py`, chain currently at lines 358-392: the
`webhook_object == "whatsapp_business_account"` branch at line 360, falling
through to `webhook_object != "instagram"` at line 376 for the
skip/unhandled case). Add a `webhook_object == "page"` branch **before** the
`!= "instagram"` check, mirroring the WhatsApp branch's shape: parse comment
+ message/postback events, look up `FacebookPage` by page ID, dispatch into
your new comment-matching + AI functions (Section 4). Do not touch the
`"instagram"` or `"whatsapp_business_account"` branches, or anything inside
them.

### 4. Campaign matching & AI reuse — concrete seam map

**What's actually shared (verified, zero changes needed):**
- `ai_service.py` — `generate_reply`/`build_system_prompt`/
  `build_cold_dm_system_prompt` already accept `platform: str = "instagram"`,
  and `_PLATFORM_DISPLAY_NAMES` (line ~56) **already includes
  `"facebook": "Facebook"`**. Call
  `ai_service.generate_reply(db, page_account, campaign, conversation.id, platform="facebook")`
  directly — no edits to this file needed at all.
- `conversation_service.py`'s budget/turn/handoff helpers
  (`reset_daily_budget_if_needed`, `is_budget_exhausted`, `record_ai_send`,
  `hand_off`, `resume_bot`, `increment_turn`, `touch_conversation`) are
  genuinely generic — they duck-type on the account/conversation objects
  passed in (WhatsApp already proves this: `tasks.py` passes a
  `WhatsappAccount` into functions type-hinted `InstagramAccount` with no
  issue). Call these directly from your new Facebook task; do not
  reimplement them.

**What needs one additive change:**
- `conversation_service.get_or_create_conversation`
  (`backend/app/services/conversation_service.py:13-22`) currently accepts
  `platform: str = "instagram"` and `whatsapp_account_id: uuid.UUID | None =
  None` as keyword-only params (Phase 2's addition), but has **no
  `facebook_page_id` parameter yet**. Add one, defaulting to `None`, and set
  it on the `Conversation(...)` construction alongside the existing
  `instagram_account_id`/`whatsapp_account_id` args (lines ~44-54) — same
  additive, backward-compatible shape Phase 2 used. This is the only edit
  needed to a Phase 1/2 shared file for this phase.

**What is NOT shared, by established precedent — you're writing a third
parallel copy, and that's the correct move:** Phase 2 deliberately did not
generalize the task-orchestration layer — its own code comments say so
directly (`_dispatch_whatsapp_ai_turn`'s docstring,
`backend/app/workers/tasks.py:185-193`: "A separate function rather than an
extension of `_dispatch_ai_turn`... risk[ing] the live IG bot... isn't worth
it"; `process_whatsapp_ai_conversation_turn`'s docstring, lines 1746-1760,
says the same about not branching inside `process_ai_conversation_turn`).
Follow the same pattern:
- A new `_dispatch_facebook_ai_turn` function. **Important divergence from
  WhatsApp's version**: Facebook has a real campaign concept (unlike
  WhatsApp, which is always cold-DM-shaped), so `_dispatch_facebook_ai_turn`
  should mirror **`_dispatch_ai_turn`'s campaign-aware shape**
  (`backend/app/workers/tasks.py:99-176` — takes `campaign` as a parameter,
  branches on whether it's `None`), not `_dispatch_whatsapp_ai_turn`'s
  always-`campaign_id=None` shape (`backend/app/workers/tasks.py:178-249`).
  When it creates the inbound `Message` row, set `facebook_campaign_id`/
  `facebook_comment_id` (Section 1) instead of `campaign_id`/`comment_id` —
  leave those two NULL for every Facebook message, same as
  `whatsapp_account_id` leaves `instagram_account_id` NULL on `Lead`.
- A new `_process_facebook_comment_events`/`_process_facebook_message_events`
  pair (or one combined function) for the webhook loop — your own
  Facebook-specific version of the campaign-matching + lead/conversation
  creation logic, using a new `facebook_campaign_matcher.py` (mirror
  `campaign_matcher.py`'s functions but querying `FacebookCampaign`/
  `FacebookCampaignKeyword` by `facebook_page_id`, per Section 1's reasoning
  for why `campaign_matcher.py` itself can't be extended).
- A new `process_facebook_ai_conversation_turn` Celery task, mirroring
  `process_ai_conversation_turn`'s structure (not the simpler WhatsApp one,
  since Facebook has the same campaign-vs-cold_dm branch IG does) but using
  `FacebookPage`, `facebook_token_service.get_decrypted_token`, and your new
  `facebook_client.py`'s send method in place of the Instagram equivalents.

### 5. Dashboard

**Already ready, zero changes needed:**
- `dashboard/lib/types.ts`'s `Platform` type already includes `"facebook"`.
- `dashboard/components/ui/PlatformBadge.tsx` already has
  `facebook: "Facebook"` in its label map — it will render correctly the
  moment real Facebook rows exist.

**One-line additions:**
- `dashboard/components/leads/LeadFilters.tsx`'s platform `<Select>`
  (currently hardcoded to `instagram`/`whatsapp` options only) — add a third
  `<option value="facebook">Facebook</option>`.
- `dashboard/app/(dashboard)/conversations/page.tsx`'s `PLATFORM_FILTERS`
  tuple (currently `["all", "instagram", "whatsapp"] as const`) — add
  `"facebook"`.

**Needs real additions:**
- Add `FacebookPage` and `FacebookAISettingsPayload` types to `types.ts`
  (mirror `WhatsappAccount`/`WhatsappAISettingsPayload`, but with the fuller
  Instagram-shaped field set per Section 1 — including `ai_cold_dm_enabled`).
- Add `facebook_page_id`/`facebook_page_username` to the `Lead` and
  `Conversation` types (mirror the existing `whatsapp_account_id`/
  `whatsapp_account_username` fields).
- `dashboard/app/(dashboard)/leads/page.tsx`'s `AccountCell` currently falls
  back `lead.instagram_account_username || lead.whatsapp_account_username`
  (added in Phase 2) — extend to a third fallback,
  `|| lead.facebook_page_username`.
- Facebook connect flow, mirroring whichever OAuth pattern the research spike
  confirms (Section header above) — if it's the config_id/popup shape,
  `dashboard/components/accounts/WhatsappConnect.tsx` is your template; if
  it's the redirect shape, follow `accounts/page.tsx`'s existing
  `connectInstagram()` function instead. Either way, a Page-picker step is
  new UI Instagram/WhatsApp didn't need (a user can grant access to multiple
  Pages in one flow).
- Facebook campaign builder — the design doc explicitly says not to force a
  shared component if the fields diverge enough (no `follow_prompt` fields
  per the research spike, `post_id` instead of `media_id`, etc.) — a separate
  `FacebookCampaignForm.tsx` is the right call here, not a retrofit of
  `CampaignForm.tsx`.
- Account-level AI settings form for Facebook Pages (mirror the WhatsApp one
  in `accounts/page.tsx`, adding the `ai_cold_dm_enabled` toggle Instagram's
  form has that WhatsApp's doesn't).

## Verification before you consider this done
- Full backend suite: compare the failure **list** against the current
  baseline you captured before starting — identical plus whatever new tests
  this phase adds, zero new failures among existing tests.
- Confirm zero changes to `process_ai_conversation_turn`, the three IG
  parsers, the `"instagram"` dispatcher branch, `_dispatch_whatsapp_ai_turn`,
  `_process_whatsapp_message_events`, `process_whatsapp_ai_conversation_turn`,
  and the `"whatsapp_business_account"` dispatcher branch — trace and show
  the diff summary. Confirm `get_or_create_conversation`'s one additive
  change doesn't alter behavior for existing Instagram/WhatsApp call sites
  (run `test_ai_continuation_dispatch.py` and the WhatsApp dispatch/turn test
  files from Phase 2 unmodified, confirm they still pass).
- Confirm the FK-constraint migration didn't hit the duplicate-FK gotcha
  Phase 2 hit — verify via `sa.inspect(engine).get_foreign_keys(...)` that
  each of `leads`/`conversations`/`automation_logs` has exactly one
  `facebook_page_id` FK after a fresh-DB migration run, not two.
- End-to-end trace: inbound Facebook comment on a tracked post → keyword
  match against `facebook_campaigns` → private reply sent via
  `recipient.comment_id` → (if the user replies) AI conversation continues
  via `recipient.id`. Show this trace with mocked/sandboxed data. Since this
  phase skips the follow-gate flow, there's no postback-tap step to trace —
  confirm that's an intentional simplification in your summary, not an
  oversight.
- Confirm the "one private reply per comment" constraint is enforced via the
  new `uq_message_facebook_campaign_comment_type` constraint on `messages`
  (Section 1) — write a test that inserts two `final_delivery` messages for
  the same `facebook_campaign_id`/`facebook_comment_id` pair and confirms the
  second raises an `IntegrityError`, mirroring however the existing
  `uq_message_campaign_comment_type` behavior is (or isn't) already tested
  for Instagram.

## Deliverable
1. The research spike findings (the three items above) — confirm or correct
   the preliminary findings, before schema work continues.
2. Behavioral verification summary — what was built, what's reused vs. new
   (referencing the seam map in Section 4), explicit confirmation the
   Instagram and WhatsApp paths are untouched, and the before/after test
   failure list against the baseline you captured at the start.
