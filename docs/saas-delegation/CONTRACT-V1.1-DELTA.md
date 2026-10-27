# Contract v1.1 delta (amends docs/17 v1)

Status: ADOPTED (ADR-023). Proposed 2026-10-26 from the Phase 6 review; adopted by the owner on the SaaS side (branch `feature/phase-6-channels`) as ADR-023, which also carries A14. A15 is an owner-assumed default and is being implemented on the SaaS side in parallel. Where this delta and CONTRACT-V1.md differ, this delta wins. Anything not mentioned stays as in v1.

A1. Channel must match. `message.received.channel` MUST equal the connection's channel. Otherwise the SaaS returns `422` (signed, malformed; Many must not retry).

A2. Status duty. After Meta accepts a message Many MUST send `message.status` `sent`; on rejection `failed` with an `error_code`. `delivered`/`read` only where the platform reports them (WhatsApp always; Messenger/Instagram only if Many subscribes to the receipts). The SaaS treats the `202` from `/api/saas/messages` as "accepted by Many", not "sent". A message with a Many id and no status for 15 minutes is shown as `unconfirmed` (neutral state); any later real status overrides it.

A3. Error codes. `error_code` enum gains `message_too_long`. Many maps Meta errors by code/subcode, never by message text (Meta localizes text). Starting table (VERIFY each against the current Meta docs before relying on it):
- WhatsApp: 131047 -> `window_closed`; 131026 -> `recipient_unreachable`; 130429/131056 -> `rate_limited`; template errors 132000-132015 and 131058 -> `template_required`; 190 -> `channel_disconnected`.
- Messenger/Instagram: code 10 with subcode 2534022 (outside allowed window) or 2018278 -> `window_closed`; code 100 with subcode 2018001 (no matching user) -> `recipient_unreachable`; codes 4, 17, 32, 613 -> `rate_limited`; 190, 102 -> `channel_disconnected`.
- Anything else -> `unknown`, with a short `error_detail` that contains no personal data.

A4. Length. The SaaS splits long replies per channel: WhatsApp and Messenger 1000 characters, Instagram 900 UTF-8 bytes (Instagram text is limited in bytes). Many must never truncate silently: if a message still exceeds the platform limit it fails permanently with `message_too_long`.

A5. What Many forwards. Forward every genuine customer DM of a delegated channel: free text and unsupported types (voice, image, sticker, etc). Do NOT forward Many-owned automation traffic: follow-gate postbacks/quick replies owned by Many flows, WhatsApp consent commands (STOP/START/opt-out keywords, handled by Many for compliance), echoes/own-page messages, delivery/read receipts, reactions. Placement in Many: after identity resolution and inbound storage, BEFORE any Many AI gate (`ai_enabled`, `ai_cold_dm_enabled`, `campaign.ai_enabled`, `lead_source`, turn limit, daily cap). Many's account `status != connected` still blocks (nothing can be sent anyway) and must be reported as degraded health.

A6. Identifiers. `external_contact_id` = IGSID / PSID / WhatsApp wa_id (stable per channel). `external_conversation_id` = Many's `conversations.id` as a string. Many creates or resolves the conversation row BEFORE forwarding, so the id exists. `external_message_id` = Meta's message id (`mid` / `wamid`), or Many's stable derived id when Meta provides none.

A7. Ordering. Many forwards events of one conversation in order: a retrying earlier message blocks later ones of that conversation (bounded by the 24 h retry budget; after that the earlier event is marked failed and the queue continues). The SaaS processes events of one conversation one at a time (row lock) in order of receipt.

A8. Loop and flood guard. SaaS: more than 15 inbound messages per minute from one contact on one connection are stored, flagged `waiting_human`, and get no AI reply; at most one busy/quota reply per conversation per 10 minutes. Many: never forward echoes or messages authored by the business itself.

A9. Health freshness. The SaaS 5-minute pull is the freshness source, so Many's signed health endpoint is mandatory (not optional). Many's push heartbeat (<= 6 h) and transition events remain. The SaaS stale threshold stays 15 minutes: with no event and no successful poll it shows `unknown/stale`.

A10. Clock safety. The SaaS clamps `received_at` to `[now-24h, now+5min]`; outside that range it uses its own receipt time.

A11. Campaign origin. WhatsApp: outreach campaign name and the rendered template body. Instagram/Facebook comment-to-DM: campaign name and the DM text Many delivered. `campaign_ref` stays opaque. Sent on every forwarded message of a campaign-origin conversation until the SaaS has stored it once (the SaaS keeps the first).

A12. Rotation (clarification). During the 24 h grace window each side accepts either secret on inbound and signs outbound with the NEW secret. Many stores current and previous secret with the previous expiry.

A13. Delegation off. Turning delegation off in Many returns the channel to today's behaviour immediately. Messages already queued for forwarding are dropped after the switch (logged), never sent to the SaaS afterwards.

A14. SaaS-side behaviour Many must respect (already built on the SaaS side).
- Retention: channel event payloads are purged at the tenant's retention cutoff; the dedupe record (connection_id, event_id) is kept 30 days.
- Origin caps (A11) are enforced by the SaaS: `campaign_name` <= 120, `opening_message_text` <= 2000, `campaign_ref` <= 128, all of them strings; anything else is a signed `422` (Many must not retry). The SaaS fences the opening message, caps it at 500 characters and gives it to the bot as untrusted context only.
- The SaaS sends `Accept-Encoding: identity`: Many must not compress the `202` body. A `Retry-After` from Many is honoured by the SaaS up to 300 s.
- The health response (section 5.2) is capped at 64 KB by the SaaS.
- A pushed `channel.status` with an `occurred_at` in the future counts as now.
- SaaS-local delivery codes outside Many's `error_code` enum (A3): `connection_paused`, `connection_revoked`, `secret_unavailable`, `many_unreachable`, `invalid_many_target`, and `many_auth_rejected` (A15). Many never sends these.
- A second secret rotation inside 24 h keeps only the newest and the immediately previous secret.

A15. A 401 from the receiver is retryable for the sender (owner-assumed default), because secret rotation makes the two sides disagree for a while.
- Many -> SaaS: retry a `401` with the normal backoff inside the 24 h budget, mark the channel degraded with `saas_last_forward_status = auth_rejected`, and keep the payload. This amends section 6 of v1 ("do not retry other 4xx"); every other 4xx stays permanent.
- SaaS -> Many: a `401` is retried inside the SaaS retry budget (about 9 minutes), then the message is failed with `many_auth_rejected`. All other 4xx stay permanent.
- Rotation runbook: pause the SaaS connection, rotate the secret in the SaaS, enter the new secret in Many, resume the connection.
