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

## Identity limitation ? R1 remains PARTIAL

The callback subject is the connecting admin's **app-scoped user ID**. It is not
a Facebook Page ID, WhatsApp WABA/phone ID or an Instagram business ID. The current
OAuth flows do not persist a proven callback-subject-to-channel mapping.
Facebook token verification currently discards `debug_token.data.user_id`;
Instagram's short-token `user_id` namespace and WhatsApp's connecting admin need
separate authoritative confirmation. Public Meta callback/debug documentation
was inaccessible during implementation (429 or tool-inaccessible). No identity
semantics or live callback success is claimed from that failure.

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
OAuth mapping capture is complete. Reconnection must re-verify the current grant.
Rotating `APP_SECRET_KEY` changes subject digests; retain a secure operator plan
to re-verify/rebuild mappings and reconcile prior receipts rather than losing
pending requests silently.

## Erase and verify before completion

1. Open an operator case for the receipt UUID and set a deadline thirty days from
   the verified request. Identify whether the request concerns the connecting
   business admin, one end customer, or the whole business workspace. Confirm the
   exact workspace/channel identities before any mutation. Email intake is
   `privacy@theosirislabs.com`; never ask for passwords or tokens by email.
2. For admin deauthorization, confirm the mapped channel is disconnected, AI and
   delegation are off, stored tokens are physically absent and ordinary queued
   forwards cannot run. Confirm other workspaces remain intact.
3. For admin/account erasure, use the approved account-deletion operation and
   verify profile, account, token and related raw payload data. Instagram has a
   hard-delete operation; its final scope and test evidence must be checked.
   Facebook/WhatsApp equivalent full admin-account erasure is not supplied by
   this callback patch. If a supported scoped operation is absent, keep the
   receipt pending and escalate for an approved implementation. Do not use ad hoc
   SQL or mark receipt completed to conceal this gap.
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
remediation, full admin-account erasure and cross-application staging evidence
remain required close-out work.
