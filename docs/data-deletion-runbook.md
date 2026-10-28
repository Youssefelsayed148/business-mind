# Verified deletion and Meta callback operations

This runbook covers receipt, identity checks and operator completion. It does not
claim the deployed services or cross-application erasure have been verified.
Callback acceptance, a database row, a 202 or a delivery queue entry is never
proof of completed erasure. Live operations require owner approval.

## Callback URLs and authentication

Configure the appropriate Meta app namespace only after staging verification:

- Instagram app: `POST {MANY_PUBLIC_BASE}/meta/compliance/instagram/deauthorize`
  and `POST {MANY_PUBLIC_BASE}/meta/compliance/instagram/data-deletion`.
- Facebook app (Pages and WhatsApp): the same paths with `facebook`.
- Deletion receipt/status: `/meta/data-deletion/status/{confirmation_code}`.
  The unguessable URL discloses only pending or operator-confirmed completion,
  with no names, channel IDs, messages or tenant details. Do not publish it.

Callbacks accept only a bounded form-encoded `signed_request`, validate
HMAC-SHA256 against that namespace's app secret, require a numeric string
`user_id`, and never store the signed request or raw user ID. Identical callback
replay reuses its durable receipt. The configured public base URL, never the
incoming Host header, supplies the status URL. Verify public HTTPS and ingress
routing before configuring Meta.

## Provider identity and unresolved grants

OAuth stores encrypted typed provider context and an encrypted subject, with
an app/namespace/subject-HMAC lookup. Facebook keeps its verified debug-token
user response and provider Page grants. WhatsApp verifies the token app, WABA
and phone grant. Instagram keeps the exchange subject and distinct profile IDs.
Wrong apps, missing subjects and mismatched grants are rejected before a local
account/token/mapping transaction commits. Reconnect replaces the previous grant.
Instagram OAuth state binds the authorized workspace; old state nonces must be
restarted after this upgrade.

Only a verified `app_user` namespace can match signed callback `user_id`.
WhatsApp Embedded Signup and Instagram provider IDs remain `unresolved` under
the owner-approved policy. They appear in `list-pending`; neither a Page, WABA,
phone, profile/business ID nor browser data proves callback identity. Legacy
rows remain unresolved without an inferred backfill. Authorized operators may
record an explicit mapping only after verifying the app-user namespace AND grant.

An unmapped valid callback is durably recorded as `operator_action`. It does not
guess which account to disconnect or erase. For a verified explicit mapping, the
callback physically deletes the matching stored tokens, disconnects that account,
turns AI and delegation off and drops pending ordinary forwards. It preserves
A16 erasure outbox events. Data erasure remains pending for operator verification.
The channel lookup requires both stored workspace ID and channel ID; another
workspace's account cannot be affected by a mismatched mapping.

## Authorized local operator CLI

Use the backend's approved environment and an authorized database identity with
only the required access. Provision `META_COMPLIANCE_DATABASE_URL` securely; the
CLI never falls back to `DATABASE_URL` and never prints the URL. Do not put secrets
in shell commands or transcripts. Commands are dry-run unless `--apply` is added.
No command below was run against a deployed service.

List pending receipts (prints request UUID, kind and status only):

```sh
python -m app.services.meta_compliance list-pending
```

For a requester, independently establish the app ID, app-scoped admin ID, granted
business channel and workspace using authorized provider records or an approved
reconnection/debug flow. A dashboard login or matching Page/phone/Instagram ID is
not sufficient proof. Record only a sanitized evidence reference in the operator
case record; never record tokens, raw signed requests or messages there. If proof
is unavailable, keep the request pending and escalate; do not invent a mapping.

Find pending requests for that verified subject. Supply the subject on stdin,
not in shell history:

```sh
python -m app.services.meta_compliance list-pending --app facebook --subject-stdin --verified-provider-identity
```

Record an explicit verified mapping; use `--app instagram --platform instagram`
for the Instagram app, and `--app facebook --platform facebook|whatsapp` for the
Facebook app. Supply the verified subject on stdin. First dry-run, then repeat
with `--apply` after the authorized operator checks the selected workspace and
channel. This replaces that channel's current grant ownership. Pending receipts
for the verified subject are reconciled immediately, removing tokens and disabling
the affected channel. No provider request or customer message is sent.

```sh
python -m app.services.meta_compliance map --app facebook --platform facebook --workspace-id <WORKSPACE_UUID> --channel-id <CHANNEL_UUID> --verified-provider-identity
```

The explicit mapping table is an operator remediation tool, not a claim that
every provider namespace is callback-compatible. Reconnection must re-verify the current grant.
Rotating `APP_SECRET_KEY` changes subject digests; retain a secure operator plan
to re-verify/rebuild mappings and reconcile prior receipts rather than losing
pending requests silently.

## Erase and verify before completion

1. Open an operator case for the receipt UUID and set a deadline thirty days from
   the verified request. Identify whether the request concerns the connecting
   business admin, one end customer, or the whole business workspace. Confirm the
   exact workspace/channel identities before any mutation. Email intake is
   [OWNER INPUT: verified privacy contact]; never ask for passwords or tokens.
2. For admin deauthorization, confirm the mapped channel is disconnected, AI and
   delegation are off, stored tokens are physically absent and ordinary queued
   forwards cannot run. Confirm other workspaces remain intact.
3. For Facebook/WhatsApp account erasure, use the owner-only R1 hard-delete
   routes and follow both phases below. Verify profile, account, token and raw
   payload removal, and remote cleanup separately. Instagram retains its existing
   hard-delete operation and requires coordinated A16/customer cleanup first.
   Do not use ad hoc SQL or mark a receipt completed to bypass pending work.
4. For an end customer, use the separately verified tenant/channel-scoped Many
   erasure operation. Confirm matching leads, conversations, messages, raw
   webhook payloads and ordinary pending forwards are erased or cleared. Confirm
   tenant B and unrelated contacts remain unchanged.
5. For delegated data, verify the SaaS contact inside the connection's tenant.
   Until A16 is verified in both deployed services, an authorized SaaS operator
   uses contact erasure with `erase_messages=true`, purges matching stored channel
   payloads and pending inbound/send work, and verifies messages cannot reappear.
   A16 acceptance alone does not establish worker completion. Revoked connections,
   missing identity proofs and exhausted retries require operator remediation.
6. Record sanitized counts and completion evidence for both applications, plus
   any lawful retained records and their basis. Do not retain message bodies or
   raw external identifiers in the audit. If no SaaS data ever existed, record
   that verified fact instead of pretending a SaaS erase ran.
7. Only after all applicable steps are verified, dry-run the completion command,
   then repeat with `--apply` under the approved operator access. The two flags
   attest independently checked outcomes; the CLI does not infer them from a
   queue response. Completion is audited and removes the subject's explicit
   mapping records. The minimal receipt remains for status/audit; this patch
   does not impose a universal receipt retention period.

```sh
python -m app.services.meta_compliance complete --request-id <REQUEST_UUID> --many-erasure-confirmed --saas-erasure-confirmed
```

Review pending cases daily, investigate failures immediately and notify the
requester if verification, legal retention or technical remediation delays
completion beyond thirty days. Owner sign-off is needed before publishing policy
text or configuring live callback URLs. Real Meta callbacks, legacy mapping
remediation, deployed account-erasure rehearsal and cross-application staging evidence
remain required close-out work.


## R1 Facebook/WhatsApp account-erasure lifecycle

Workspace owners call `DELETE /facebook/accounts/{id}/hard` or
`DELETE /whatsapp/accounts/{id}/hard`. Both return 202 with an opaque `job_id`;
replays reuse it while retained, and another workspace receives 404. This starts
local erasure; it does not mark a Meta deletion receipt completed.

Phase 1 locks the channel, sets `erasure_pending`, removes Meta tokens, disables
AI/delegation/outreach, cancels ordinary queued work and enumerates delegated
identities, including queued-only identities and WhatsApp contacts without leads.
It queues/reuses A16 events and deletes scoped customer rows in one transaction.
The disabled account retains only the signing configuration needed for remote
acceptance. Existing pending/failed A16 work is retained for remediation.

The regular forwarding sweep advances jobs. Phase 2 removes the remaining account
rows and the authorization map in one transaction only after every linked A16
has HTTP 202 acceptance or independently verified SaaS cleanup. A16 202 is durable
acceptance, never completion. Public receipts remain pending until the separate
operator completion workflow. Completed minimal jobs are purged only thirty days
after independently verified SaaS cleanup. Pending failures are never purged.

Missing signing configuration, unknown historical remote scope, failed/missing
A16 events or unscoped historical audit text require operator action. Never
attribute audit content by a matching name/email. Sent legacy A16 rows have no
proof of an exact 202 and need operator verification. Inspect both applications
and record sanitized completion evidence before attesting. After verifying local
scope and SaaS cleanup, dry-run, review, then apply the following local command:

```sh
python -m app.services.meta_compliance verify-account-erasure --job-id <JOB_UUID> --many-erasure-confirmed --saas-erasure-confirmed
```

Add `--apply` only under approved operator access. This command does not contact
the SaaS or Meta. Independently complete the callback receipt using `complete`
after all applicable accounts and customer copies are verified erased. A16
acceptance alone does not justify either confirmation flag.

Deploy migration `0030_meta_account_erasure` after `0029_hash_processed_event_keys`
with processing paused. Downgrade fails closed while any job lacks verified remote
cleanup or local completion. Use pause/forward repair rather than discarding
pending jobs. The empty-install bootstrap preserves the pre-0030 authorization
shape so historical migration 0028 can validate before 0030 runs.

The legacy Instagram hard-delete endpoint retains its existing immediate
account-removal behavior. For delegated Instagram use the verified customer A16
workflow and coordinate remote cleanup before account removal; do not use it to
bypass outstanding erasure work. Instagram dispatch/send handlers and `59d3442`
were not modified by R1. In-flight handler/worker memory still requires the
quiescence and independent verification steps above; deletion cannot recall sends.
