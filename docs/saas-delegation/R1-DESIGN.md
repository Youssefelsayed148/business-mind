# R1: OAuth ownership and account erasure - owner-approved design

2026-10-28. Owner approved this schema, migration 0030 and two-phase lifecycle,
including unresolved provider subjects, in the implementation request. A5 v26.0
is owner-approved. The design preserves the adopted A16 contract. Local evidence
is recorded in R1-IMPLEMENTATION.md; deployed behavior remains UNVERIFIED.

## Verified starting points

- `meta_authorizations` stores an app-scoped subject HMAC tied to workspace,
  platform and channel, with one current grant per channel. OAuth does not fill it.
- Facebook `verify_user_access_token()` checks validity/app ID but discards the
  debug response. The Page grant list supplies Page IDs. WhatsApp stores WABA
  and phone IDs from signup and number metadata, but records no connecting user.
- Instagram token exchange returns provider data; profile normalization merges
  `user_id`/`id`. Neither account ID is proof of the callback subject namespace.
- Verified callbacks already revoke mapped tokens, disable delegation and return
  200 idempotently. Unknown subjects stay in the operator ledger.
- Instagram hard-delete orders outbound links/messages/conversations/leads
  before account deletion and scrubs just that account's raw webhook entries.
  It deletes all forwarding rows. The forwarder cannot deliver A16 if its
  account row is gone. Copying that behavior into FB/WA would lose erasure work.

## Proposed OAuth mapping

Use a typed `MetaGrantIdentity`, populated only from server-to-provider results:
app ID, provider subject, subject namespace, channel grant IDs and optional
business/Page/WABA/phone IDs actually returned by the API. Reject wrong app,
invalid/missing subject or mismatched grants before committing a verified map.
Never trust an admin ID, Page ID or business ID supplied by the browser as proof.

Extend MetaAuthorization with nullable encrypted subject and encrypted typed
provider context, and a constrained `subject_namespace` (`app_user`,
`business_system_user`, `unresolved`). Keep the HMAC for lookup; index app ID,
namespace and digest. Do not expose these fields in account responses or logs.
Legacy rows stay unresolved until reverified; no account-ID-based backfill.

At OAuth connect/reconnect, verify the provider subject and channel grant,
then atomically store account/token/mapping; existing token helpers must support
`commit=False`. Preserve the operator mapping path with explicit provider proof.
Connect routes update only the authorized workspace; reconnect replaces the
current grant. Callback matching uses app ID + verified app-user namespace +
subject HMAC, never Page/WABA/phone/profile equality. Replay behavior and generic
verification failures remain unchanged; verified deauthorize receives 200 even
when no safe mapping exists, leaving a visible operator case.

**Blocking identity evidence:** the current source does not prove that an
Embedded Signup business/system-user subject, or either Instagram profile ID,
equals the deauthorize `signed_request.user_id`. The four relevant public Meta
pages were retried: debug_token/deauth returned 429; Instagram Business Login
and Embedded Signup overview were inaccessible. No authenticated lookup is
authorized. Recommended policy: store verified provider context but keep
unproven callback mappings unresolved for operator verification. This does not
close R1's automatic mapping requirement for those flows. The owner approved
this policy: store provider context, keep the callback namespace unresolved, and
expose the grant in the operator ledger. Never infer a callback mapping.

## Proposed account erasure

Add owner-permission routes `DELETE /facebook/accounts/{id}/hard` and
`DELETE /whatsapp/accounts/{id}/hard`, using existing workspace `delete_accounts`
authorization (currently owner only). Reuse a common scoped FK deletion service
derived from Instagram's map, without modifying Instagram dispatch/send handlers.
Return 202 with an opaque durable job ID while local account erasure is pending;
replays return that job without repeating remote work. Cross-workspace is 404.

Create a durable account-erasure job per workspace/platform/channel/request UUID.
It holds status, receipt linkage, counts and fixed error codes; no tokens,
external identities or customer text. Proposed states: `pending`,
`waiting_remote_acceptance`, `local_erased`, `operator_action`. Channel UUID is
not an account FK, so the job survives account removal. Retain completed minimal
jobs 30 days after separately verified completion; pending failures are not purged.

Phase 1 locks the channel, sets `erasure_pending`, removes Meta tokens, disables
AI/delegation/outreach, drops ordinary forwards and cancels sends. It enumerates
all delegated identities, including queued payload identities and WhatsApp
contacts without leads, and atomically queues/reuses A16 erasures before deleting
customer data. Duplicate identities produce one event per request. Signing
configuration stays only in Many's disabled account until remote acceptance;
there is no new credential store or Meta token sent to SaaS. Unknown historical
remote scope/missing signing configuration is operator_action, never completion.

Phase 2 runs only after all applicable A16 events are accepted, or an operator
has independently verified SaaS cleanup. It deletes the account and remaining
related rows. A16 202 proves durable acceptance only: the public deletion receipt
stays pending until SaaS completion is independently verified through the
existing operator workflow. Exhaustion uses the existing 24-hour budget and
visible operator remediation. Preserve the runbook's in-flight quiescence
requirement; no claim that this recalls sent messages or cancels worker memory.

Deletion order / additional FB and WA ownership:

1. Collect scoped campaigns, contacts, leads, conversations and messages;
   outbound idempotency links before messages, conversations before leads.
2. FB: campaign keywords/cooldowns, messages/comments, leads, campaigns, tokens,
   profile/account. WA: campaign recipients (including message-only outreach),
   consent events, contacts, messages/conversations/leads, campaigns before
   templates, tokens and account. Clear nullable references before parents.
3. Delete scoped automation logs; scrub audit content proven linked by selected
   entity IDs, retaining only fixed action/count metadata. Never delete a shared
   app User or audit records merely because an email/name matches. Historical
   audit content without provable scope requires operator review.
4. Scrub only target-account entries from mixed raw webhook deliveries; retain
   other accounts and opaque dedupe markers. Delete ordinary forwarding rows
   and outbound links; clear accepted A16 payloads before removing their outbox
   rows, preserving only opaque event IDs/counts in the erasure job.
5. Remove the channel's authorization map and account last, one transaction.
   Retry jobs/late callbacks cannot recreate erased content; fresh OAuth is
   blocked while erasure_pending. No Meta/AI send is part of erasure.

## Migration and verification gate

Proposed Alembic `0030_meta_account_erasure`, parent
`0029_hash_processed_event_keys`: mapping fields/index/constraints plus durable
job table. Reversible schema; no inferred identity backfill, no reconstruction
of erased personal data. Downgrade requires processing paused and pending jobs
resolved; fail closed rather than drop pending erasure jobs.

Required tests: typed provider response failures, app/subject namespace mismatch,
connect/reconnect atomic rollback, deauthorize replay/unknown subject/three
platforms, owner-only and workspace A/B erasure, all FK children above, mixed
webhook payloads, conversations + saas_forward_events + saas_outbound_messages,
pending/failed A16 preservation and acceptance-only status, concurrency/stale
jobs, ordinary delegation-off behavior, and migration upgrade/downgrade/drift.
Use only fresh private DB/Redis and mocked HTTP. Full suite once after final
integration; owner-run Meta/canary and separate feature merge approval remain.

**Approval recorded:** migration 0030 and the lifecycle above are approved.
See R1-IMPLEMENTATION.md for tested implementation and remaining live gates.
