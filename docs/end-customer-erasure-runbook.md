# End-customer erasure across Many and the SaaS

Status: local implementation and fake-SaaS tests only. Live execution, in-flight
worker quiescence and remote completion are UNVERIFIED. This runbook does not
authorize deployments, live sends, provider calls or changes to a customer system.

## Scope and preparation

An owner/admin must verify the requester's right to request erasure and identify
the business workspace, platform, channel account and exact external identity.
Use IGSID for Instagram, PSID for Messenger and wa_id for WhatsApp. Facebook
campaign ASID aliases are resolved through the same scoped lead when PSID is
known. Never perform a global phone/customer-ID lookup or merge identities across
workspaces. Keep the identity in the authorized privacy case, outside repository,
chat, shell history, screenshots and ordinary application logs.

For an active channel, arrange an owner-approved maintenance window: pause the
SaaS connection and quiesce applicable Many inbound/send/campaign workers. Turning
delegation off alone returns the channel to Many's native automation, so do not
use it as a substitute for quiescing workers or disabling that channel's native
AI/campaign work. The API removes stored pending work; it cannot recall a request
already in memory or a message already delivered to Meta. Its advisory locks
coordinate with queued SaaS-forward workers; live Instagram handlers do not
participate in an erasure lock. Verify queues are drained before completing a
high-assurance erase, and check for new rows before resuming.

## Many admin operation

Use an authenticated admin API client; there is no new dashboard button in this
change. Send `POST /privacy/contact-erasure/{platform}/{channel_id}` with the
selected `X-Workspace-Id` header and JSON containing `request_id` (a fresh UUID)
and `external_contact_id`. Reuse that request UUID and identity if the same
request fails in transport. Do not log request bodies. Workspace owner/admin
membership is checked server-side; unrelated channels return 404.

The single transaction deletes scoped leads, conversations/messages, related
comments/cooldowns and identifiable automation logs, WhatsApp outreach
contacts/consent/recipient data, outbound references, and the customer's raw
webhook items. Other accounts/customers within the same delivery are preserved.
Ordinary queued forwards are dropped and their payloads cleared; stored terminal
forward payloads are cleared too. A content-free `contact.erasure` event is
persisted in the same transaction. A missing local identity is idempotent.

A 202 response has an opaque `event_id`, `local_status: erased`, and one of:

- `remote_status: queued`: durable work exists, picked up by the ordinary forward
  sweep. No Meta send or AI generation is triggered by this erasure action.
- `remote_status: operator_action_required`: local erasure committed, but the
  original signing configuration is unavailable or forwarding has failed. The
  durable outbox record must be remediated; remote erasure is not complete.
- `remote_status: accepted_not_completed`: the SaaS accepted the signed event.
  Its background erasure job still needs independent completion verification.

The event contains only the A16 envelope, connection ID and external contact ID;
it contains no name, message, separate phone field, tenant or bot ID. It survives
local lead deletion and the delegated-chat switch being disabled, while the
original signing configuration exists. Never delete the channel or its signing
configuration until remote erasure has been verified.

Use `GET /privacy/contact-erasure/{platform}/{channel_id}/{event_id}` for sanitized
forwarding state. This endpoint never claims the SaaS completed the erasure.
The same POST is idempotent for its request UUID, channel and input identity.
A later, new request must use a new request UUID.

## SaaS completion and interim manual operation

Until both A16 implementations and the staging integration are verified:

1. Verify the exact connection belongs to the intended tenant and bot.
2. In the SaaS's authorized admin workflow erase that tenant's contact with
   `erase_messages=true`. Also purge stored channel-event payloads for the
   identity and cancel pending inbound/outbound jobs/sends. The old standalone
   contact route by itself does not prove those additional items were purged.
3. If linked identities were explicitly merged, cover the resulting contact's
   conversations/messages within that tenant. Never erase another tenant.
4. Verify the erasure job/audit completion, absence of customer content in kept
   accounting records, and cancellation of pending work. Record event/request
   IDs, counts, timestamp and operator sign-off without customer identifiers,
   message bodies, tokens or signature headers.

An accepted or duplicate 202 from the signed event receiver is not evidence of
completion. A revoked connection returns generic 401 and requires operator
handling. No new remote-completion callback is defined by A16.

## Failures and retry

The forwarder retries network failures, 5xx, 429 and 401 inside its existing
24-hour budget, preserving event ID and re-signing with the current secret.
An exhausted budget is an operator-action failure. After correcting the
original connection/configuration, an admin may explicitly POST
`/privacy/contact-erasure/{platform}/{channel_id}/{event_id}/retry`; this works
with delegated chat disabled. It resets that erasure's retry budget only.

The event's connection cannot be silently changed to a replacement connection.
If the original connection was missing, verify the correct tenant/connection and
submit a new erasure request after repair, or follow the manual workflow. Failed
payloads currently follow the existing seven-day policy; terminal outbox rows
follow the existing thirty-day policy. A purged payload cannot be replayed from
that row. Preserve a secured privacy case until completion; the application
must not present queue acceptance or exhausted retries as completed erasure.

## Retention and limitations

The existing daily retention task also clears raw `webhook_events.payload`
after thirty days, returning/logging only a cleared count. Dedupe/status rows
remain. This is scheduled source configuration, not proof a deployed beat/worker
has run. Verify the production scheduler separately with approval.

Migration0029 hashes legacy `processed_webhook_events.event_key` values into
versioned SHA-256 tombstones and irreversibly clears diagnostic metadata. The
shared helper stores only the same opaque keys and allowlisted event types;
future raw-key, metadata or unrecognized event-type inserts are refused by database checks. Existing replay
protection remains, including legacy/raw-plus-hashed collisions; a duplicate
cannot claim processing again. These deterministic hashes are pseudonymous
replay markers, not a claim that hashing makes all data anonymous.

Rollout requires an approved maintenance window: pause all old API/worker writers,
apply0028 then0029 with the pre-deploy backup procedure, deploy the matching new
helper in every writer, verify the constraints and hashed-only storage, then
resume. Do not run an old writer after the migration. It will be refused by the
new guards; it cannot use the hashed markers for legacy dedupe. Downgrade removes
the new schema guards only and never restores raw identifiers or excerpts.
Code rollback to an old raw-key writer requires keeping processing paused and
an explicitly reviewed recovery plan; do not remove the guards and resume old
workers. Backup/replica copies made before0029 still require their established
retention controls.

This transaction does not erase provider inboxes, backups, historical external
logs or customer-controlled copies. Existing platform handlers can still emit
their existing operational log fields; no live Instagram handler was refactored
by this approved shared-helper change. Apply the established backup/log retention
and restore process and reapply completed privacy requests after restoration.
No backup deletion or live migration was performed here.
