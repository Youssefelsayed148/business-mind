# Meta App Review submission pack ? close-out draft

App: ManyOsirisChat, Meta app `1321099496095662`. This is a review preparation
checklist, not a record of Meta approval, live permission activity or completed
recordings. The code facts below are locally inspectable; current Meta dashboard
configuration, permission eligibility and public deployment state remain
UNVERIFIED until the owner records evidence. Do not submit this draft unchanged.

## Product and delegation description

ManyOsirisChat helps a specific business manage Instagram, Facebook Page and
WhatsApp customer support, keyword campaigns and lead follow-up. Optional AI
answers business questions from that business's instructions and knowledge. It
is not a general-purpose AI assistant. The business controls campaigns and is
responsible for required consent.

Many owns Meta authorization, encrypted tokens, webhooks, messaging windows,
opt-in and message delivery. A business may enable delegation to the Osiris Labs
SaaS chatbot for a selected channel. Many then forwards genuine inbound customer
messages, stable identities and limited campaign context to that SaaS, which
operates reply generation, inbox and human handoff. Many does not run its own AI
or takeover controls for that delegated channel. A queued callback or accepted
reply is not proof of delivery. Delegation is off by default.

Support replies respect the applicable 24-hour window; automated and AI replies
do not use a human-agent tag to extend it. WhatsApp sends outside an open service
window require approved templates and applicable opt-in. State these limits in
the submission form and recordings.

## Permissions to reconcile against the dashboard

The following describe existing code usage, not an authoritative ruling that a
permission will receive Advanced Access. Check each requested scope and allowed
use against the current official submission form before requesting it.

| Permission | Code workflow to demonstrate |
|---|---|
| `instagram_business_basic` | Instagram Login; connected account metadata; campaign media picker; token refresh |
| `instagram_business_manage_messages` | Customer-triggered comment private reply and an inbound DM followed by a business reply |
| `instagram_business_manage_comments` | Keyword campaign public reply under the connected business's comment |
| `pages_show_list` | Login for Business grants; list and connect the authorized Page |
| `pages_manage_metadata` | Subscribe the connected Page to feed/messages/postbacks |
| `pages_messaging` | Page private reply and Messenger support conversation |
| `pages_read_engagement` | Confirm the dashboard/official requirement for the Page feed/private-reply workflow before requesting |
| `whatsapp_business_messaging` | Customer service reply; approved opted-in template send where applicable |
| `whatsapp_business_management` | Connect/subscription, number metadata/health and template management |

Instagram scopes are requested in code. Facebook and WhatsApp grants come from
separate Meta Login-for-Business/Embedded Signup configurations and cannot be
proved from repository settings. Remove `pages_manage_engagement` from the
Facebook login configuration: current code does not create/edit/delete Page
comments or likes. Do not request unused content-publishing or Page-post scopes.

Graph version is configured by `META_GRAPH_API_VERSION` (current source default
`v21.0`). A supported-version/changelog check is still required: official Meta
version documents returned HTTP 429/inaccessible during this close-out. No live
API compatibility result or retirement date has been established here.

## Privacy, deauthorization and deletion

Public policy pages are `/privacy` and `/terms`; the privacy deletion instructions
are `/privacy#data-deletion`. The policy discloses the SaaS processor, optional AI,
separate stored copies, retention and operator-coordinated deletion.

Callback source paths are:

- Instagram app: `/meta/compliance/instagram/deauthorize` and
  `/meta/compliance/instagram/data-deletion`.
- Facebook app for Pages/WhatsApp: the same paths with `facebook`.
- Returned public status URL: `/meta/data-deletion/status/{confirmation_code}`.

**R1 is PARTIAL.** Signed callbacks are validated and durably received. Known
operator-verified admin-to-channel mappings allow targeted token deletion,
disconnection and delegation disablement. Existing OAuth does not yet establish
all callback-subject mappings. Unmapped or full account-erasure requests remain
operator-action cases; the public page says pending. Never tell reviewers that
acceptance means full erasure. See [the operator runbook](data-deletion-runbook.md).

A16 `contact.erasure` is the adopted cross-application end-customer erasure
contract. Its implementation and deployed execution must be verified separately.
The signed connection determines tenant scope; acceptance means durably queued,
not completed. Until verified in both deployments, operators coordinate Many
erasure, tenant-scoped SaaS contact/message erasure and stored-payload cleanup.
Do not present the callback or A16 as fully operational without that evidence.

## Recordings and reviewer test instructions

Use dedicated business/test accounts and synthetic customer data. Record at
1080p with clear English narration/captions and the browser URL visible. Keep
tokens, signing secrets, real customer data and credentials out of every frame.
Provide reviewer access securely through the submission workflow, not this repo.

For each permission, show the native Many workflow from connection/authorization
to the result that depends on that permission. Verify actual consent scope text
in the dashboard. Confirm `META_MOCK_PRIVATE_REPLIES=false` for an approved live
recording; mock success does not establish Meta API activity.

1. Instagram basic: authorize the business, show metadata and campaign media
   selection. Messaging: customer comments the campaign keyword, receives the
   private reply, then sends a DM; show the business reply in the native inbox.
   Comments: show the configured public reply under the customer's comment.
2. Facebook: show Page grants and selection, webhook subscription and a customer
   comment/private reply plus Messenger conversation. Demonstrate only requested
   scopes; confirm which engagement permission is required from official rules.
3. WhatsApp: show approved test-number Embedded Signup, health/template metadata,
   an allow-listed customer's inbound message and reply, and an approved template
   to an opted-in test recipient where that permission requires it.
4. Delegation scene: enable delegation on the approved test channel, show one
   inbound message in the SaaS, a bot reply and human handoff/agent reply through
   Many, plus delivery outcome. Show that Many's own takeover is unavailable.
5. Privacy/deletion: show the published instructions and a real approved test-user
   callback/status workflow once mappings and erasure are verified. Do not
   manufacture completion or record a pending case as a successful erase.

Each live send, deployment, paid AI call and authenticated provider action needs
separate owner approval. These instructions authorize no execution by themselves.
D5 (Instagram unsupported-message diff) stays OPEN per owner instruction and must
be listed in the Batch A close-out report. D4 recording presentation is still an
owner review item; no recordings were made in this patch.

## Owner checklist before submission

- [ ] Confirm Business Verification and Tech Provider requirements/status.
- [ ] Reconcile requested scopes and webhook fields with the actual dashboard;
  remove `pages_manage_engagement` and unused scopes.
- [ ] Verify a supported Graph version and endpoint compatibility.
- [ ] Verify public policy/contact/support URLs and correct app icon/category.
- [ ] Complete admin mapping/legacy remediation and full erasure gaps, rehearse
  callbacks and confirm returned status URL is publicly reachable over HTTPS.
- [ ] Verify A16 completion in both staging apps or disclose operator handling.
- [ ] Finish the staging canary and sanitized evidence for delivery, rotation,
  replay, 429, expiry, takeover guard and rollback.
- [ ] Record permission-specific native flows and delegated conversation; collect
  actual successful API activity per the current review requirements.
- [ ] Create reviewer test access and supply exact steps and expected results.
- [ ] Owner reviews policy/submission text, approves recordings and approves
  submission. No dashboard settings, credentials, messages or application changes
  were published by this preparation patch.
