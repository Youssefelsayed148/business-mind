# Claude Code prompt — Phase 1: Multi-Platform Foundation

Read `docs/specs/2026-09-05-multi-platform-expansion-design.md` first (or wherever
it lives in this repo — it may not be under `docs/specs/` yet). Follow it exactly —
especially Section 3 (Foundation approach) and Section 5 (cross-cutting principles).
Only implement Phase 1 from Section 4. Do not start Phase 2 or 3 work.

This file has been re-verified against the actual codebase as of 2026-09-05
(migrations up to `0010_cold_dm_ai`). File/line references below were confirmed
by reading the real files, not assumed — but re-check them yourself before editing,
since the repo may have moved on since this was written.

## Hard constraints
- Do NOT modify the `instagram_accounts`, `campaigns`, or `comments` tables/models
  in any way.
- Do NOT change any existing Instagram service, route, or worker logic.
- Do NOT add new columns to `InstagramAccount`.
- Every existing test must still pass unmodified after this change.

## Scope for this session only

### 1. Migration

New Alembic revision file: `backend/alembic/versions/0011_platform_foundation.py`,
`revision = "0011_platform_foundation"`, `down_revision = "0010_cold_dm_ai"`.

Follow the exact idempotent-migration pattern already used in
`0009_ai_conversation_layer.py` and `0010_cold_dm_ai.py`: a `_columns(table)`
helper via `sa.inspect(bind).get_columns(table)`, and an `_add_column_if_missing`
helper, so the migration is safe to re-run against a partially-applied DB. Copy
these helpers rather than reinventing them.

**`leads.platform` and `conversations.platform`:**
- `sa.Column("platform", sa.String(50), nullable=False, server_default="instagram")`.
- **Important:** do NOT use `sa.Enum` / a native Postgres `ENUM` type. Nothing
  else in this codebase uses one — `leads.lead_source`, `instagram_accounts.status`,
  `instagram_accounts.business_vertical` are all plain `String(50)` columns with a
  code comment documenting the allowed values (see `lead.py:33-35` and
  `instagram_account.py:25`). A native enum would also require an
  `ALTER TYPE ... ADD VALUE` migration in Phase 2/3 instead of just inserting rows
  — stay consistent with the existing convention. Add the same style of comment:
  `# 'instagram' | 'whatsapp' | 'facebook'`.
- After adding the column, run an explicit backfill statement
  (`UPDATE leads SET platform = 'instagram' WHERE platform IS NULL`) even though
  `server_default` covers it — this mirrors the defensive backfill pattern in
  `0010_cold_dm_ai.py:69`.

**`whatsapp_account_id` and `facebook_page_id` on both tables:**
- Plain nullable `PGUUID(as_uuid=True)` columns, no FK constraint (the target
  tables `whatsapp_accounts` / `facebook_pages` don't exist yet — they're created
  in Phase 2/3, which will add the FK constraint at that point via
  `op.create_foreign_key`).
- Add a code comment above each column noting the FK is deferred to its phase.

**CHECK constraint (both tables), via `op.create_check_constraint`:**
```
(platform = 'instagram' AND instagram_account_id IS NOT NULL
   AND whatsapp_account_id IS NULL AND facebook_page_id IS NULL)
OR (platform = 'whatsapp' AND whatsapp_account_id IS NOT NULL
   AND instagram_account_id IS NULL AND facebook_page_id IS NULL)
OR (platform = 'facebook' AND facebook_page_id IS NOT NULL
   AND instagram_account_id IS NULL AND whatsapp_account_id IS NULL)
```
- **Flag this explicitly in a migration comment, don't silently leave it implicit:**
  `leads.instagram_account_id` and `conversations.instagram_account_id` are
  currently `nullable=False` (see `lead.py:28-30`, `conversation.py:39-41`) and
  this migration must NOT relax that — the hard constraint above only protects
  `instagram_accounts`/`campaigns`/`comments`, but touching `instagram_account_id`'s
  nullability on `leads`/`conversations` is out of scope for Phase 1 regardless.
  The practical effect: the CHECK constraint above is satisfiable today only by
  `platform = 'instagram'` rows (since `instagram_account_id` can never be NULL
  yet), which is correct and matches "zero behavior change." It will become
  possible to insert real `whatsapp`/`facebook` rows only after a **Phase 2
  migration relaxes `instagram_account_id` to nullable on `leads`/`conversations`**
  — write this down in the migration docstring so it isn't rediscovered mid-Phase-2,
  per Section 5's "investigate-before-code" principle.

**`downgrade()`:** drop the CHECK constraints first, then the four new columns,
mirroring `0010_cold_dm_ai.py`'s downgrade pattern (drop only additive columns,
use `_drop_column_if_present`).

### 2. Webhook dispatcher branch — `backend/app/workers/tasks.py`

Confirmed current shape of `process_webhook_event` (starts at line 175): after
the `event = db.query(WebhookEvent)...first()` null-check (line 178-181) and
`log_action(db, "webhook_received", ...)` (line 183), it unconditionally calls:
```python
comment_events = parse_instagram_comment_events(event.payload or {})
postback_events = parse_instagram_postback_events(event.payload or {})
message_events = parse_instagram_message_events(event.payload or {})
```
(lines 185-187), then has a skip path if all three are empty (lines 188-192):
```python
if not comment_events and not postback_events and not message_events:
    event.processing_status = "skipped"
    db.commit()
    log_action(db, "webhook_skipped", details={"reason": "no_comment_postback_or_message_events", "event_id": webhook_event_id})
    return
```

Add the new branch **immediately before** the three parser calls (i.e. right
after the `log_action(db, "webhook_received", ...)` line), gating on
`event.payload.get("object")`:
- `"instagram"` → fall through to the existing three parser calls, completely
  unchanged.
- Anything else (`None`, missing key, `"whatsapp_business_account"`, `"page"`,
  or any unrecognized value) → mirror the existing skip pattern exactly:
  `logger.info("Unhandled or missing webhook object type", extra={"object": event.payload.get("object") if event.payload else None, "event_id": webhook_event_id})`,
  then `event.processing_status = "skipped"`, `db.commit()`, and
  `log_action(db, "webhook_skipped", details={"reason": "unhandled_webhook_object", "object": ..., "event_id": webhook_event_id})`, then `return`.
- Do not touch the internals of `parse_instagram_comment_events`,
  `parse_instagram_postback_events`, or `parse_instagram_message_events`.

**Confirmed safe for existing tests:** every existing webhook payload fixture in
`test_webhook_processing.py`, `test_meta_webhooks.py`, `test_cold_dm_ai_dispatch.py`,
and `test_ai_continuation_dispatch.py` already sets `"object": "instagram"` in its
payload dict, so this branch is a no-op for all current tests — no existing test
payload needs to change. Add 1-2 new tests (matching the existing test files'
style) covering: `object` missing entirely, and `object` set to something else
(e.g. `"page"`) — both should result in `processing_status == "skipped"` and the
three IG parsers never being called (you can assert this by spying/mocking, or
simply by asserting no `Comment`/`Lead`/`Message` rows are created).

### 3. Dashboard

**Types** — `dashboard/lib/types.ts`: add `platform?: string | null;` to the
`Conversation` type (next to `lead_source` at line 114) and to the `Lead` type
(next to `lead_source` at line 166), matching the existing optional/nullable
style used for `lead_source`.

**Badge component — read this before writing one:** there is currently no
shared badge component for this concept. `SourceBadge` is duplicated as a
local, unexported function in *both* `dashboard/app/(dashboard)/leads/page.tsx`
(lines 29-40) and `dashboard/app/(dashboard)/conversations/page.tsx` (lines 20-30)
— two near-identical copies with slightly different Tailwind spacing
(`px-2.5 py-1` vs `px-2 py-0.5`). Do not add a third copy-pasted local function.
Instead create one shared component, `dashboard/components/ui/PlatformBadge.tsx`,
following the exported-function pattern used by `components/ui/Badge.tsx`:
- Props: `{ platform }: { platform?: string | null }`.
- Label map: `{ instagram: "Instagram", whatsapp: "WhatsApp", facebook: "Facebook" }`,
  falling back to the raw value (title-cased) for anything unrecognized, same
  defensive style as `Badge.tsx`'s `statusLabel`.
- Icon: skip it. The installed `lucide-react` (1.16.0, see `dashboard/package.json`)
  ships no brand icons — no `Instagram`/`Facebook`/`WhatsApp` export exists in
  this version — and no existing badge in the app (`Badge.tsx`, `SourceBadge`)
  uses an icon anyway. Text-only pill, consistent with those.
- Visual style: reuse the rounded-full bordered pill pattern from `Badge.tsx`/
  `SourceBadge` (`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold`)
  so it looks native next to the existing `SourceBadge` in the same rows.

**Wire it in:**
- `leads/page.tsx`: add a `<th className={thClass}>Platform</th>` to the header
  row (currently `Username | Source | Source Campaign | Captured Keyword |
  Instagram Account | Captured At`, lines 125-130) — place it right after
  "Username" — and a matching `<td>` rendering `<PlatformBadge platform={lead.platform} />`
  next to the existing `<SourceBadge source={lead.lead_source} />` call (line 143).
- `conversations/page.tsx`: same treatment on its header row (`Status | Lead |
  Source | Campaign | Turns | Last activity`, lines 134-139) and body row (near
  line 156, next to the existing `<SourceBadge source={conversation.lead_source} />`).
- Do not touch `accounts/page.tsx` — Phase 1 scope per the design doc is Leads
  and Conversations only.

**Filter dropdown:** skip it, per the design doc — a visible badge is the
Phase 1 requirement; filtering waits for Phase 2 when there's more than one
real platform. Flag in your summary if you think it'd genuinely be trivial to
add now, but don't do it unless asked.

## Verification before you consider this done
- Run the full backend suite (`pytest` from `backend/`) — confirm 100% pass,
  no skipped-because-broken. Pay particular attention to
  `test_webhook_processing.py`, `test_meta_webhooks.py`, `test_cold_dm_ai_dispatch.py`,
  `test_ai_continuation_dispatch.py`, `test_comment_parser.py`, and `test_models.py`
  since these touch the tables/paths you're changing.
- Run `npm run build` in `dashboard/` (or `npx tsc --noEmit` if you want a
  faster check) — there's no dedicated typecheck script, `next build` type-checks
  as part of the production build.
- Manually trace: does a real Instagram webhook payload (`"object": "instagram"`)
  still flow through `process_webhook_event` identically to before (same parser
  calls, same account lookup, same comment/lead/conversation creation)? Show me
  the relevant code path (with your new branch included) as part of your summary
  so I can confirm nothing changed for IG.
- Confirm the migration backfills existing rows correctly: after running
  `alembic upgrade head` against a copy of real/dev data (or in your test DB
  fixture), spot-check that no existing lead or conversation ends up with
  `platform` NULL or with more/fewer than one of the three account FKs set,
  and that the CHECK constraint didn't reject any existing row on migration.
- Confirm `alembic downgrade -1` from `0011_platform_foundation` cleanly reverses
  everything it added.

## Deliverable
Behavioral verification summary (as per our usual workflow) — what changed,
what was deliberately left untouched, and confirmation the IG path is
byte-for-byte identical. Also call out the Phase 2 prerequisite noted above
(relaxing `instagram_account_id` nullability on `leads`/`conversations`) so it
isn't lost before that phase starts. I'll commit and push locally, then deploy
on the VPS.
