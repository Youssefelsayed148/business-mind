# A16 proposed amendment — owner confirmation required

Status: ADOPTED by the owner, 2026-10-28. Canonical clauses are synchronized
into contract v1 section 11 and both v1.1 delta copies. Implementation and
runtime erasure remain UNVERIFIED until B2/C2 evidence is recorded.

A16. End-customer erasure. Many may send `contact.erasure` to the existing
signed events endpoint. The version-1 envelope contains `event_id` (max 128),
`event_type: "contact.erasure"`, `connection_id`, `occurred_at` (UTC), and
`external_contact_id` (the same channel identity used by `message.received`).
It contains no separate name or phone field, message body, tenant id, or bot id. The connection
and identity fields are required; blank or malformed fields return 422.

Authentication, body-size limits, rotation, rate limits, and deduplication are
unchanged. The signed connection header and body must identify the same
connection. Tenant scope comes only from the authenticated connection.
Active and paused connections accept erasure; revoked connections retain the
existing generic 401 behavior and require operator handling.

The SaaS resolves the identity by `(connection.tenant_id, connection.id,
external_contact_id)`, never by a global external-id lookup. It erases that
contact and its messages and personal contact fields, purges stored event
payloads for that identity, and cancels pending channel jobs/sends associated
with the erased contact. If contacts were explicitly merged, the erasure
covers the resulting contact and its linked conversations/messages within
that tenant; it never affects another tenant. Conversation records retained
for accounting must contain no erased customer content or identity. Pending
pre-erasure inbound work must not recreate the erased content after completion.

Acceptance and durable job storage return `202 {"status":"accepted"}`;
duplicate acceptance returns `202 {"status":"duplicate"}`. Acceptance is not
proof that erasure has completed. A missing identity is an idempotent success.
Processing is transactional; transient processing failures use durable job
retries and must remain visible for operator remediation. Audit completion
without message bodies, external identifiers, or secrets. Retain the existing
event-id dedupe record for at least 30 days with its payload cleared.

Many erases the matching local customer data, raw webhook payloads and pending
ordinary forwards, and durably queues this event atomically. Its erasure event
must survive local customer deletion and remain sendable while delegation is
disabled, provided the connection's signing configuration remains available.
Use the existing signed forward retry policy (including the 24-hour budget);
exhaustion is an explicit operator-action failure, never reported as completed.
Never send a Meta message or generate an AI reply as part of erasure.

Until both sides are verified, use the documented operator process: erase in
Many, erase the tenant-scoped SaaS contact with `erase_messages=true`, purge
the identity's stored channel payloads, and record sanitized completion evidence.
