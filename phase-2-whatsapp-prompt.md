# Claude Code prompt — Phase 2: WhatsApp Cloud API (reactive AI only)

Read `docs/specs/2026-09-05-multi-platform-expansion-design.md` first — especially
Section 4 Phase 2 and Section 5 (cross-cutting principles). Only implement Phase 2.
Do not start Facebook (Phase 3) work.

**Phase 1 is merged and verified** (migration `0011_platform_foundation`, the
`payload["object"]` dispatcher branch in `process_webhook_event`, `platform`
exposed on the Leads/Conversations dashboard APIs, platform badge in the UI).
The current backend test baseline is **23 pre-existing failures, unrelated to
the multi-platform work** (infra/test-isolation gaps: no Celery eager-mode
config anywhere in the repo, so any test that posts to `/webhooks/meta` and
expects synchronous side effects without mocking the dispatch will fail
regardless of what Phase 2 does — see `test_webhook_processing.py`,
`test_send_private_reply.py`, `test_meta_integration.py`,
`test_instagram_routes.py`, `test_message_retry.py`,
`test_campaign_routes.py`/`test_campaigns.py`). Don't chase these — compare
your before/after failure **list**, not the raw count, and confirm it's
unchanged apart from whatever this phase's own new tests add.

This file was re-verified line-by-line against the actual current repo
(2026-09-05, post-Phase-1) — the seams and gotchas below are read from real
code, not guessed. Still, re-check line numbers before editing; re-verify
anything that looks off rather than trusting this doc blindly.

## Hard constraints
- Do NOT modify `instagram_accounts`, `campaigns`, `comments`, or any existing
  Instagram service/route/worker logic. **`process_ai_conversation_turn` in
  `tasks.py` is absolutely off-limits** — do not add an
  `if conversation.platform == "whatsapp"` branch inside it, see Section 4
  for why and what to write instead.
- Do NOT change the existing three Instagram webhook parsers, or the
  `"instagram"` branch of the Phase 1 object-dispatcher.
- The one sanctioned exception to "don't touch shared code": Section 4 below
  identifies exactly three small, additive, default-preserving extensions to
  shared functions (`conversation_service.get_or_create_conversation`,
  `_dispatch_ai_turn`, `ai_service.py`'s prompt builders) that are safe and
  necessary. "Additive" means: every existing call site keeps compiling and
  behaving identically with no changes, because the new parameter defaults
  to the Instagram-preserving value. Anything beyond what Section 4
  describes is out of bounds — if you find yourself needing to change more
  than a function signature plus one new conditional branch in any of these
  three, stop and flag it rather than proceeding.
- WhatsApp gets its own tables, own parser, own service, own Celery task — no
  shared mutation of IG-only tables/columns beyond what Phase 1 already added.
- Direct Meta WhatsApp Cloud API only — no BSP (Twilio/360dialog).
- Reactive only: bot replies to inbound user messages within the 24-hour
  window. No template-based outbound broadcasts, no proactive campaigns.
- Single phone number per workspace for this phase — no multi-number UI.

## Scope for this session only

### 1. Data model

**New `whatsapp_accounts` table**, modeled on `InstagramAccount`'s shape
(`backend/app/models/instagram_account.py`): `id`, `workspace_id` (FK),
`phone_number_id`, `display_phone_number`, `whatsapp_business_account_id`,
`status`, plus the same AI-settings columns `InstagramAccount` has:
`ai_enabled`, `ai_business_profile`, `ai_tone_instructions`,
`ai_daily_message_cap`, `ai_handoff_after_turns`, `ai_messages_sent_today`,
`ai_budget_reset_at`. No campaign fields, no `ai_cold_dm_enabled` (every
WhatsApp conversation is cold-DM-shaped by nature — there's no separate
opt-in to gate).

**New `whatsapp_tokens` table — do not extend `MetaToken`.** Confirmed by
reading `backend/app/models/meta_token.py` and `backend/app/services/token_service.py`:
`MetaToken.instagram_account_id` is `NOT NULL` with an FK strictly to
`instagram_accounts.id`, and every function in `token_service.py`
(`store_encrypted_token`, `get_decrypted_token`, `mark_token_expiring_soon`,
etc.) takes `instagram_account_id` as a *named* parameter, not a generic
account reference. Generalizing this touches Instagram's token storage
directly, which the hard constraints above forbid. Create
`whatsapp_tokens` (same shape: `access_token` encrypted via the existing
`app/utils/crypto.py` helpers, `status`, `expires_at`) and a parallel
`whatsapp_token_service.py` with the same function shapes. This matches the
design doc's own principle: new platforms get new tables, full stop.

**Migration, in order:**
1. Create `whatsapp_accounts`, `whatsapp_tokens`.
2. Add the FK constraints Phase 1 deferred: `leads.whatsapp_account_id` and
   `conversations.whatsapp_account_id` → `whatsapp_accounts.id`.
3. **Relax `instagram_account_id` to nullable on `leads` and `conversations`.**
   Phase 1's CHECK constraint (`ck_leads_platform_account_fk` /
   `ck_conversations_platform_account_fk`) already requires
   `instagram_account_id IS NULL` for `platform='whatsapp'` rows, but the
   column itself is still `NOT NULL` — no WhatsApp row can be inserted until
   this is relaxed. This is the one schema change in this phase that touches
   a column also used by Instagram: after relaxing it, update the SQLAlchemy
   model type hints in `lead.py`/`conversation.py` from
   `Mapped[uuid.UUID]` to `Mapped[uuid.UUID | None]` for `instagram_account_id`
   to match (currently wrong now that NULL is possible). Verify: (a) every
   existing Instagram row still has its `instagram_account_id` populated —
   relaxing NOT NULL doesn't touch existing values, and (b) a test insert
   with `platform='whatsapp'`, `instagram_account_id=NULL`,
   `whatsapp_account_id=<uuid>` succeeds and satisfies the CHECK constraint.
4. **Add a WhatsApp-scoped uniqueness constraint on `leads` — currently
   missing, easy to miss.** `Lead.__table_args__` has
   `UniqueConstraint("workspace_id", "instagram_account_id", "ig_user_id", name="uq_lead_workspace_instagram_user")`.
   Postgres unique constraints treat NULL as distinct from every other NULL,
   so once `instagram_account_id` is nullable, this constraint provides
   **zero duplicate protection for WhatsApp leads** — every WhatsApp row has
   `instagram_account_id IS NULL`, so Postgres never compares them against
   each other under this constraint. Add a second constraint,
   `UniqueConstraint("workspace_id", "whatsapp_account_id", "ig_user_id", name="uq_lead_workspace_whatsapp_user")`
   — by the same NULL-distinctness rule, this one only actually constrains
   rows where `whatsapp_account_id` is set (i.e. WhatsApp rows), leaving
   Instagram rows untouched. Add both the model-level `CheckConstraint`
   companion in `lead.py` and the migration DDL.
5. **Add `automation_logs.whatsapp_account_id` (nullable, FK to
   `whatsapp_accounts.id`).** `AutomationLog.instagram_account_id`
   (`backend/app/models/automation_log.py`) is FK'd strictly to
   `instagram_accounts.id` — passing a WhatsApp account's UUID into that
   column would be a foreign-key violation, not just semantically wrong. The
   `log_action()` helper (`backend/app/services/log_service.py`) will need a
   new optional `whatsapp_account_id` parameter alongside the existing
   `instagram_account_id` one so WhatsApp-path calls populate the correct
   column. This preserves per-account AI observability for WhatsApp the same
   way it exists for Instagram today (recent commit history shows this was
   deliberately built out for Instagram — don't regress it for WhatsApp by
   silently dropping account attribution from its logs).

**Naming note, not a fix:** `Lead.ig_user_id` / `Lead.ig_username` will be
reused to store the WhatsApp user's WA ID / profile name for `platform='whatsapp'`
rows (the design doc doesn't rename these, and renaming risks touching the
~22 backend files that read `ig_user_id` for Instagram). This is intentional
reuse, not an oversight — leave a code comment on the column saying so, so
the next reader isn't confused.

### 2. Meta integration
- New `app/integrations/meta/whatsapp_oauth.py` or equivalent — WhatsApp Cloud
  API uses Facebook Login for Business + Embedded Signup for number
  registration, which differs from Instagram Login. Instagram's own flow
  (`backend/app/integrations/meta/oauth.py` — `build_oauth_url`,
  `exchange_code_for_short_lived_token`, `exchange_for_long_lived_token`,
  wired up in `backend/app/api/routes_meta.py` at `GET /meta/connect/start`
  and `GET /meta/connect/callback`) is a real, complete implementation, not a
  placeholder — a good structural pattern to mirror for the route shape, but
  note it's Instagram-Login-specific (hits `www.instagram.com`/
  `api.instagram.com`/`graph.instagram.com`), so the actual OAuth
  provider/endpoints/scopes for WhatsApp's Facebook Login for Business will
  be entirely different. Research the current Meta docs for the exact flow
  before implementing; flag any ambiguity rather than guessing.
- New webhook parser for `payload["object"] == "whatsapp_business_account"` —
  parse inbound text messages (mirror the shape/spirit of
  `parse_instagram_message_events` in `backend/app/integrations/meta/webhooks.py`,
  adapted to WhatsApp Cloud API's webhook format: `entry[].changes[].value.messages[]`).
- New `app/integrations/meta/whatsapp_client.py` for sending messages via the
  Cloud API (`POST /{phone_number_id}/messages`). `MetaMessagingClient`
  (`backend/app/integrations/meta/messaging.py`) is not reusable as a base —
  its `__init__` hardcodes `base_url = f"https://graph.instagram.com/{settings.META_GRAPH_API_VERSION}"`
  (line ~38) and its `send_direct_message`/`get_username` signatures are
  IG-shaped (`ig_user_id`, IGSID). Write a fresh client, but reuse
  `MetaMessageResult` (same file, a plain `{success, provider_message_id,
  raw_response, error_code, error_message}` value object with no IG-specific
  fields) as the return type for your send function — that keeps the
  outbound-`Message`-row-creation code identical in shape to the Instagram
  path (see Section 4).

### 3. Webhook dispatch
The Phase 1 object-branch lives in `process_webhook_event`
(`backend/app/workers/tasks.py`, function starts ~line 174). **Important:**
the actual inbound-message handling for Instagram is not a separate,
reusable function — it's a ~250-line inline block (`for msg_evt in
message_events:`, roughly lines 490-741) directly inside
`process_webhook_event`, doing: dedup → look up `InstagramAccount` → check
`account.ai_enabled` → find-or-create `Lead` (cold-DM path inline, including
a username lookup via `MetaMessagingClient`) → branch on
`lead.lead_source` (`"campaign"` vs `"cold_dm"`) → call `_dispatch_ai_turn`.

For WhatsApp, write your own equivalent block (extracting it into a proper
named function, e.g. `_process_whatsapp_message_events`, is a reasonable and
low-risk improvement over the IG code's shape — encouraged, since you're
writing this fresh rather than editing the delicate existing block). It's
simpler than the IG version: every WhatsApp conversation is cold-DM-shaped,
so there's no `lead_source == "campaign"` branch to replicate — just
account lookup → `account.ai_enabled` check → find-or-create `Lead`
(`platform='whatsapp'`, `whatsapp_account_id=account.id`,
`instagram_account_id=None`) → dispatch.

Wire it into the Phase 1 branch:
`"whatsapp_business_account"` → new WhatsApp parser → look up
`WhatsappAccount` by `phone_number_id` → your new message-handling block.
Do not modify the `"instagram"` branch or anything in the existing
`for msg_evt in message_events:` loop — the only sanctioned touch to shared
code from this section is the additive `_dispatch_ai_turn` extension
described in Section 4, and even that should be a signature change plus one
new branch, nothing more.

### 4. AI conversation reuse — concrete seam map

This is the highest-risk part of Phase 2 because the existing AI-turn
pipeline is more deeply Instagram-coupled than it looks. Read this before
writing the WhatsApp send path:

- **`conversation_service.get_or_create_conversation`**
  (`backend/app/services/conversation_service.py:13`) — signature is
  `(db, workspace_id, lead_id, campaign_id, instagram_account_id)`, and
  unconditionally does `Conversation(..., instagram_account_id=instagram_account_id, ...)`
  with no `platform` argument at all (relies on the model's `platform`
  default, which is `"instagram"`). **Must be extended** — add a `platform`
  parameter (default `"instagram"` to keep every existing call site
  unchanged) and a `whatsapp_account_id` parameter, and set the right column
  based on `platform`. Do not change the default behavior for existing callers.

- **`_dispatch_ai_turn`** (`tasks.py:95`) — untyped `account`/`lead`/`campaign`
  params (good, duck-typing-friendly), but its body hardcodes
  `conversation_service.get_or_create_conversation(db, ..., instagram_account_id=account.id)`
  (line ~117). Calling this as-is with a `WhatsappAccount` would try to
  insert that account's UUID into `instagram_account_id`, which after step 3
  above is nullable but still FK'd to `instagram_accounts` — a foreign-key
  violation, not a silent bug, but still wrong. Either extend
  `_dispatch_ai_turn` with a `platform` kwarg that it forwards to the
  now-extended `get_or_create_conversation` (touches shared code, but the
  change is additive/backward-compatible — default `platform="instagram"`
  preserves every existing call site byte-for-byte), or write a small
  WhatsApp-specific equivalent. Prefer extending `_dispatch_ai_turn` itself
  here (unlike `process_ai_conversation_turn` below) since the change is
  small, additive, and keeps conversation-creation logic in one place —
  but show the diff clearly before proceeding, since it's still a shared file.

- **`process_ai_conversation_turn`** (`tasks.py:1337`) — this is the actual
  Celery task that generates and sends the AI reply, and it is **not**
  platform-agnostic despite the handoff/budget logic being conceptually
  generic. It hardcodes, in order: `db.query(InstagramAccount).filter(InstagramAccount.id == conversation.instagram_account_id)`
  (line ~1396-1397), `get_decrypted_token(db, account.id)` (IG-only, per
  `token_service.py` above), `MetaMessagingClient()` +
  `client.send_direct_message(access_token=..., ig_user_id=account.ig_user_id, recipient_id=lead.ig_user_id, text=...)`
  (line ~1493-1500). **Recommendation: write a new, separate
  `process_whatsapp_ai_conversation_turn` Celery task rather than adding an
  `if conversation.platform == "whatsapp"` branch inside this one.** This
  duplicates the handoff/budget/logging scaffolding (~100 lines), but the
  hard constraint says not to touch existing Instagram worker logic, and
  this function is the single most business-critical piece of the running
  system (it's what actually sends AI replies to real Instagram users today)
  — a bug introduced while branching inside it risks the live IG bot, for a
  DRY-ness gain that isn't worth that risk. The pieces that *are* safely
  reusable as-is (genuinely duck-typed, no IG-specific field access):
  `conversation_service.reset_daily_budget_if_needed` /
  `is_budget_exhausted` / `record_ai_send` (only touch
  `ai_budget_reset_at`/`ai_messages_sent_today`/`ai_daily_message_cap`,
  which `whatsapp_accounts` will also have) and `conversation_service.hand_off`
  / `resume_bot` / `increment_turn` / `touch_conversation` (operate purely
  on `Conversation`, no account type dependency at all). Call these from
  your new task instead of reimplementing them.

- **`ai_service.py`** — `generate_reply`/`build_system_prompt`/
  `build_cold_dm_system_prompt` take an untyped-enough `account` parameter
  that a `WhatsappAccount` would duck-type through structurally (same
  `business_vertical`/`ai_business_profile`/`ai_tone_instructions` fields),
  **but the prompt text itself hardcodes the platform name**:
  `_base_prompt_parts` (line ~61) says
  `f"You are a helpful assistant messaging on behalf of an Instagram business account..."`
  and `_finalize_prompt` (line ~81) appends
  `"Keep replies short and conversational, suitable for an Instagram DM."`
  Sent verbatim to WhatsApp users, this would have the bot describe itself
  as an Instagram assistant. This is the one small, safe edit to a shared
  file this phase needs: add a `platform: str = "instagram"` parameter to
  `build_system_prompt`/`build_cold_dm_system_prompt`/`generate_reply` (and
  thread it through `_base_prompt_parts`/`_finalize_prompt`) so the two
  hardcoded strings above use the passed platform's display name instead of
  a literal `"Instagram"`. Default the parameter to `"instagram"` so every
  existing call site is unaffected. Show this diff before proceeding — it's
  a shared file, but the change is narrowly scoped to two string templates.

### 5. Dashboard

- **Two existing API responses will silently serialize `None` as the string
  `"None"` for WhatsApp rows if left as-is** — confirmed by reading the
  actual code:
  `backend/app/api/routes_dashboard.py` (`list_leads`, ~line 334):
  `"instagram_account_id": str(lead.instagram_account_id)` — unguarded
  `str()` on what will be `None` for WhatsApp leads once Phase 2 ships.
  `backend/app/api/routes_conversations.py` (`_conversation_response`,
  ~line 39): same pattern, `"instagram_account_id": str(conversation.instagram_account_id)`.
  Fix both to `str(x.instagram_account_id) if x.instagram_account_id else None`
  (matches the pattern already used elsewhere in the same files for other
  nullable fields, e.g. `source_campaign_id`), and add parallel
  `whatsapp_account_id` / `whatsapp_account_username` fields following the
  same shape as the existing `instagram_account_id` / `instagram_account_username`
  ones (`_account_usernames` in `routes_dashboard.py` only queries
  `InstagramAccount` today — add an equivalent for `WhatsappAccount` rather
  than trying to generalize the existing helper, consistent with the
  separate-tables approach elsewhere in this phase).
- Update `dashboard/lib/types.ts`: add `whatsapp_account_id` /
  `whatsapp_account_username` to the `Lead` and `Conversation` types (next
  to the existing `instagram_account_id` fields), matching their optional/
  nullable style.
- WhatsApp connect flow (new page/route, mirrors the Instagram connect UX —
  the Instagram OAuth/connect flow is real and complete, see Section 2, so
  there's a working pattern to follow for the dashboard side too — check
  `dashboard/app/(dashboard)/accounts/page.tsx` for the current connect-button
  UX to mirror).
- Account-level AI settings form for the WhatsApp account (same fields/shape
  as the Instagram account settings UI).
- `PlatformBadge` (`dashboard/components/ui/PlatformBadge.tsx`, built in
  Phase 1) already renders a `"WhatsApp"` label for any non-`"instagram"`/
  `"facebook"` value via its fallback path — no change needed there. Leads
  and Conversations tables will show it automatically once real WhatsApp
  rows exist with `platform: "whatsapp"` in the API response.
- Add the platform filter dropdown now (Phase 1 deliberately skipped it with
  only one real platform live — with two, it's worth it).

## Verification before you consider this done
- Full backend suite: compare the failure **list** (not just the count)
  against the 23-failure baseline noted above — it should be identical plus
  whatever new WhatsApp-path tests you add, with zero new failures among
  existing tests.
- Confirm the `instagram_account_id` nullability change didn't alter any
  existing Instagram row or query behavior — this is the one schema change
  in this phase that touches a column also used by Instagram, so trace it
  carefully (existing rows keep their value; only new WhatsApp rows get NULL
  there).
- Confirm zero changes to `process_ai_conversation_turn`'s body, the three IG
  parsers, or the `"instagram"` dispatcher branch. For the sanctioned
  additive extensions (`get_or_create_conversation`, `_dispatch_ai_turn`,
  `ai_service.py`'s prompt builders), confirm the Instagram call paths
  produce byte-for-byte identical behavior to before — same conversation
  rows, same prompt text, same everything — by running the existing
  Instagram-path tests for these functions (`test_ai_continuation_dispatch.py`,
  `test_cold_dm_ai_dispatch.py`) unmodified and confirming they still pass.
  Show the diff summary for all three.
- Confirm the new `uq_lead_workspace_whatsapp_user` constraint actually
  rejects a duplicate WhatsApp lead insert (same workspace + whatsapp_account
  + WA ID) while leaving Instagram lead inserts unaffected.
- End-to-end trace: inbound WhatsApp message → webhook → parser → lead/
  conversation creation → AI reply generated with WhatsApp-appropriate
  prompt text → sent back via the new Cloud API client. Show this trace with
  a mocked or sandboxed example, including a check that the sent text does
  NOT contain the literal word "Instagram".
- Confirm daily AI budget cap and handoff-after-turns logic work identically
  to Instagram cold-DM, by calling the same `conversation_service` functions
  (not reimplementing the logic) — verify by test, not by inspection alone.

## Deliverable
Behavioral verification summary — what was built, what's reused vs. new
(referencing the seam map above), and explicit confirmation the Instagram
path is untouched. I'll test manually via a real WhatsApp Business test
number before this goes further.
