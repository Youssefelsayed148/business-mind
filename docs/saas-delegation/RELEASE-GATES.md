# Remaining staging, Meta review and release work

This is an execution checklist, not completed evidence. The owner authorized
autonomous local implementation and targeted checks, followed by one integrated
full-suite pass. That does not authorize deployment, authenticated service calls,
live messages, submission, paid usage, cloud resources, pushes or main merges.

## Batch D: staging evidence

Use CANARY.md only after identifying the approved staging releases and disposable
Meta test-number recipients. Record timestamps, opaque IDs and sanitized outcomes;
never tokens, message contents, recipient numbers or signatures.

| Requirement | Evidence required | Current result |
| --- | --- | --- |
| Approved staging rebuild and migration | Deployed source/image IDs, predeploy dump and restore rehearsal, actual Alembic current/head | UNVERIFIED |
| Preflight | Selected delegation enabled, canonical UUID, HTTPS URL, secret presence, independent observation of one beat, actual ingress settings | UNVERIFIED |
| Customer, bot and agent flow | One forwarded inbound, one intended reply, sent/delivery callbacks, no Many AI fallback | UNVERIFIED |
| Handoff and takeover | SaaS owns handoff; Many takeover/resume returns the documented guard | UNVERIFIED |
| Window rejection | Natural closed-window observation; distinguish local guard from actual Meta numeric errors | UNVERIFIED |
| Rotation both ways | Pause, rotate, enter new secret securely, verify grace and emergency second rotation, resume | UNVERIFIED |
| Retry and replay | Controlled retryable failure/429, stable event IDs, replay recovery, expiry releasing an ordered queue | UNVERIFIED |
| Health | Push transitions, heartbeat and successful pull; no invented runtime process evidence | UNVERIFIED |
| Erasure | Many local removal, durable A16 acceptance, SaaS completion audit, payload/job purge, unrelated tenant preserved | UNVERIFIED |
| Deauthorization | Verified admin mapping, signed callback, token removal, delegation off; unresolved mapping must remain operator action | UNVERIFIED |
| Rollback | Delegation off, SaaS paused, ordinary pending forwards dropped, erasure requests retained for remediation | UNVERIFIED |

Offline fake-peer tests prove only their tested cases. They cannot satisfy these
staging requirements. Do not add a production fault-injection endpoint to obtain
retry evidence or bypass the messaging-window guard to obtain an error code.

## Batch E: Meta dashboard and submission evidence

The owner starts Business Verification and Tech Provider status work (R6).
Public documentation lookup is permitted; authenticated dashboard actions and
real calls/screencasts still need their separate approval.

- Confirm the actual Facebook Login for Business and WhatsApp Embedded Signup
  permission configurations; remove unused pages_manage_engagement.
- Resolve Graph version support against accessible official documentation (A5).
- Confirm the final privacy/terms text, callback/status URLs, verified contact
  details and deletion operator process before publishing them.
- Confirm app subscriptions, OAuth redirects, reviewer roles and dedicated test
  accounts without recording credentials in the repo.
- Review the updated meta-app-review-submission.md against observed behavior;
  record native flows per permission plus one delegated conversation (D4).
- Use real allowed test flows with mock private replies disabled only when the
  owner approves those calls. Record one observed success per requested
  permission. No local test or queued 202 is evidence of real Meta delivery.
- Review D5 (Instagram unsupported-message commit 59d3442) with the owner;
  it remains OPEN and unchanged at the owner's request.

## Batch F: submission and enablement

Do not submit or enable channels from this checklist alone. Submission requires
the owner's approval and completed review evidence. SaaS main merge requires a
green full Playwright run and owner approval (D1). Go-live follows Meta approval,
then separately approved channel enablement, WhatsApp first, with monitoring and
the tested rollback procedure. Record actual reviewer questions and outcomes;
never mark approval or deployment from a draft plan.
