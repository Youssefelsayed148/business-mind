# 6E: End-to-end test on the Meta test number

Status: **checklist written from the repository; nothing here has been run.** The owner runs every case live on the staging stack (6B) with the Meta test number, and fills the Result column. Cases the code does not let me confirm are marked **UNVERIFIED**; for those the Expected cell says what to observe and record, not what must happen. Exit criterion (`docs/PHASE-6-PLAN.md`): written results per channel; failures triaged.

Sources read: `docs/saas-delegation/CANARY.md` and `KNOWN-LIMITS.md`, `docs/end-customer-erasure-runbook.md`, `docs/DATA-UNIFICATION.md` (sections 6, 14 to 16), `docs/whatsapp-outreach-implementation.md` and `-predeploy.md`, `docs/meta-app-review-submission.md`, and the routes `backend/app/api/routes_conversations.py`, `routes_saas_delegation.py`, `routes_contact_erasure.py`, `backend/app/services/whatsapp_webhook_service.py`, `modules/saas/apps/api/app/linking/*`.

## 0. Safety (read first)

1. **Test number and allow-listed handsets only.** Use the Meta app's free test numbers/pages/accounts and recipients registered for them. Never connect or message a customer or production number, never run outreach or campaigns, never send to anyone else.
2. **Synthetic data only.** Test messages must contain no real personal data. Do not record phone numbers, message text, tokens, secrets, signature headers or full webhook bodies in the Result column; record UTC time, opaque ids (message, conversation, event, case) and a sanitized outcome.
3. **Instagram code is exercised, never edited.** Instagram receive, dispatch and send code is frozen (`CLAUDE.md` rule 3, `scripts/check_instagram_frozen.py`). Run the Instagram cases exactly as written. If an Instagram case fails, **STOP, do not retry in a loop, do not patch anything, and report**: case id, UTC time, the exact output or log line, and the state of the flags. Any code change needs the owner's explicit OK first.
4. **Stop-and-report rule (all channels):** stop at the first unexpected 5xx on a webhook, any sign of a message going to a handset that is not on the allow-list, any real token or secret appearing in a log or screen, or a delegation flag that cannot be switched off. Switch the channel's delegation off, pause its SaaS connection, and report. Do not continue to the next case.
5. **Backup first:** run `scripts/ops/backup_all.sh --target DIR` (6C) before the first case. Nothing here needs a restore, but erasure cases (E-x6) delete data for good.
6. **Order of flags** (`docs/DEPLOY-OUTLINE.md` and the canary runbook): delegation stays off until each case says otherwise; identity and data flags (`DATA_UNIFICATION_ENABLED` included) are not enabled in staging until the Phase 3 review items are fixed or accepted in writing (`docs/PHASE-6-PLAN.md` section 2). **Case x6 needs `DATA_UNIFICATION_ENABLED=true`: do not start it until the owner has settled that item.**
7. **Delegation preconditions** (from the canary runbook): Many `APP_ENV` production mode requires HTTPS service URLs, so delegation cannot be switched on until 6A (internal TLS) is done. One beat process only. Many's own AI stays **off** on the test account before delegation is switched on and through rollback. Keep the SaaS connection paused while entering credentials.
8. **Rollback for every delegated case:** delegation off in Many for that channel, then pause the connection in SaaS (do not revoke or delete it). Queued unsent forwards are dropped, not replayed. Never delete a channel or its signing configuration before an erasure is verified.

## 1. Setup the owner must have (record, do not paste secrets)

| Item | Value or "yes" (no secrets) |
|---|---|
| Staging Many and SaaS commit | |
| Edge deny checks from outside pass (6B) | |
| Meta test number / test Page / test Instagram account connected, webhook subscribed, signature verified | |
| Recipients allow-listed (count only) | |
| `alembic current`: Many `0031_sso_link`, SaaS `0038_grant_location_scope` (heads read from files at this commit) | |
| Many native AI on the test channels: off before delegation cases | |
| SaaS bot and inbox configured for each test channel (one bot per channel account) | |
| `DATA_UNIFICATION_ENABLED` state for case x6 | |

## 2. Where to look (used in the tables)

| Where | What |
|---|---|
| Many dashboard Messages / Conversations / Leads / Logs pages (staff session) | routes `GET /messages`, `/conversations`, `/leads`, `/logs`; these global routes are staff-only |
| Many container logs | `docker compose ... logs many-api many-worker`; WhatsApp logs mask ids |
| Many delegation settings | dashboard account page "SaaS delegation"; API `GET/PATCH /{platform}/accounts/{channel_id}/saas-delegation` (platform prefix `instagram`, `facebook`, `whatsapp`) and `POST .../retry-failed` |
| SaaS inbox | web `/app/{tenant}/conversations` and the bot conversation page `/app/{tenant}/bots/{botId}/conversations/{conversationId}` |
| SaaS channel health | the channel page in the SaaS (health shown as `connected`, `degraded`, `token_expiring`), fed by signed health polls (about every 5 minutes) |
| SaaS people page | `/app/{tenant}/contacts/links` (needs `DATA_UNIFICATION_ENABLED`), API `GET /api/v1/tenants/{id}/customer-links` |
| SaaS erasure | `POST /api/v1/tenants/{id}/customer-links/{link_id}/erase`, `GET .../erasure-cases`, `POST .../erasure-cases/{id}/retry` (Owner/Admin) |
| Many erasure status | `GET /privacy/contact-erasure/{platform}/{channel_id}/{event_id}` (edge path `/api/privacy/...`) |
| Manual SQL, read only, staging DB | `docker compose ... exec pg15 psql -U many -d many` (counts only, no content) |

## 3. Case table

Column key: **Pre** precondition; **Owner action** exact steps; **Many** and **SaaS** expected result; **Look** where to check. Result stays empty until the owner fills it (PASS, FAIL, BLOCKED, with time and ids).

Common check for any bot or agent reply: a `202` from Many means accepted, **not sent**. Count a reply as sent only when the handset shows it and the status shows `sent`/`delivered` (canary rule).

### 3.1 WhatsApp (Meta test number)

| ID | Case | Pre | Owner action | Expected in Many | Expected in SaaS | Look | Result |
|---|---|---|---|---|---|---|---|
| W1 | Inbound, delegation OFF | Delegation off for the account; Many AI off | From the allow-listed handset send a synthetic text | One lead and WhatsApp contact created (consent `unknown`), one inbound message row; no reply | Nothing received | Many Leads and Messages pages; Many logs; SaaS inbox empty | |
| W2 | Bot answer, delegation OFF (Many native AI) | Many AI on for this account only for this case | Send a text matching the bot behavior | Many's own AI answers once on the handset | Nothing received | Handset; Many Messages | |
| W3 | Delegation ON: inbound and bot answer | Delegation on (canary setup order); Many AI off; SaaS bot configured | Send a text | Inbound row; forward to SaaS succeeds, pending queue drains | One inbound message and one bot answer; handset gets one answer; no Many AI answer | Handset; SaaS inbox; Many delegation page (failed/pending counts) | |
| W4 | Human reply | W3 passed | In SaaS, use the handoff trigger or inbox handoff; send another text; then send one agent reply from the SaaS inbox (window open) | Many accepts, reports `sent` | Conversation marked for human; bot stops; agent reply shown `sent` then `delivered` (real status webhook) | Handset; SaaS inbox; Many Messages | |
| W5 | Many Take Over guard (delegation ON) | W3 passed | In Many open the same conversation, press Take Over; also `POST /conversations/{id}/take-over` with an owner/admin session | UI says managed in the SaaS inbox; API answers **409**, code `CHANNEL_MANAGED_BY_SAAS`; Resume Bot guarded the same | No change | Many conversation page; API response | |
| W6 | Take Over with delegation OFF | Delegation off, Many AI on | Press Take Over, send a text, then Resume Bot | AI stops after Take Over, resumes after Resume Bot. **UNVERIFIED:** whether a human can then reply from Many (no Many send route was found for staff replies) | n/a | Many Conversations; handset | |
| W7 | Opt-out | Delegation off first, then repeat with it on | Send exactly `STOP` (default keywords: `stop`, `unsubscribe` and the Arabic forms, exact match on short messages; the account may override the list). Replay is not possible from the handset; do not replay | Contact consent becomes `opted_out` (recorded before other early exits) | With delegation on: **UNVERIFIED** whether the SaaS bot stops answering a STOP; record whether any bot reply arrived after STOP | Many `GET /whatsapp/contacts` (Owner/Admin) consent field; handset; SaaS inbox | |
| W8 | Erasure via the SaaS flow | W3 passed; link sync done (below); `DATA_UNIFICATION_ENABLED=true` (see safety 6); maintenance window per the erasure runbook (pause connection, quiesce workers) | Staff runs a link sync for the organization (`POST /api/v1/platform/tenants/{id}/customer-links/sync`, `dry_run` first). As Owner/Admin open `/app/{tenant}/contacts/links`, find the test person, press Erase, confirm | Many reports `local_status: erased`; the lead, conversation, messages, contact rows for that wa_id are gone | Link row state `erased`; case reaches `complete` (or `needs_action` with a reason, then Try again with the same request id); SaaS contact deleted | People page and Erasure requests card; `GET .../erasure-cases`; Many erasure status route; SQL counts for that lead | |
| W9 | Delegation off again (rollback) | W3 done | Delegation off in Many, pause SaaS connection | Native behavior returns; queued unsent forwards dropped | No new events | Delegation page; SaaS health | |
| W10 | Closed window | W4 done; more than 24 h since last inbound, no free-entry window | Send one plain-text agent reply from SaaS, no template | Local guard: `window_closed`, **no Meta request** (record "N/A, local guard") | Message shows failed / `window_closed` | SaaS inbox; Many logs | |
| W11 | Channel health | After resume | Wait for the next signed health poll | n/a | `connected`, fresh `checked_at`; a temporary test token may show `token_expiring` (record, refresh, re-check) | SaaS channel page | |

### 3.2 Facebook (Meta test Page)

Delegation covers Messenger as well as WhatsApp (`routes_saas_delegation.py` builds routers for all three platforms; the outbound code has a Messenger send path).

| ID | Case | Pre | Owner action | Expected in Many | Expected in SaaS | Look | Result |
|---|---|---|---|---|---|---|---|
| F1 | Inbound, delegation OFF | Page connected, delegation off, Many AI off | Message the test Page from a tester account | Lead (PSID as external id) and inbound message stored; no reply | Nothing | Many Leads, Messages, logs | |
| F2 | Bot answer, delegation OFF | Many AI on for the Page for this case | Message the Page | Many AI answers once | Nothing | Messenger; Many Messages | |
| F3 | Delegation ON: inbound and bot answer | Canary setup order done for the Page | Message the Page | Forward succeeds | One inbound and one bot answer; no Many AI answer | Messenger; SaaS inbox; delegation page | |
| F4 | Human reply | F3 passed | Handoff in SaaS; send another message; send one agent reply from the SaaS inbox | Accepted, then `sent` | Bot stops; agent reply `sent`/`delivered`. **UNVERIFIED:** whether Meta sends a delivery status for Messenger that the SaaS shows | Messenger; SaaS inbox | |
| F5 | Take Over guard | F3 passed | As W5 on the Facebook conversation | 409 `CHANNEL_MANAGED_BY_SAAS` | none | Many conversation page | |
| F6 | Opt-out | Delegation off, then on | Send `STOP` as a plain message | **UNVERIFIED:** no Messenger opt-out keyword handling was found in the code read (only the WhatsApp path has it). Record exactly what happened (bot answered or not) | Same: record | Messenger; both inboxes | |
| F7 | Erasure via SaaS flow | F3 passed; link sync done; flag and window as W8 | As W8 for the Facebook person (PSID) | `local_status: erased`; lead, conversation, messages gone | Link `erased`; case `complete` or `needs_action` | As W8 | |
| F8 | Delegation off again | F3 done | As W9 | Native behavior returns | No events | Delegation page | |

### 3.3 Instagram (Meta test account). Code is frozen: exercise only, never edit.

On any failure here: stop and report (safety 3 and 4). The Instagram channel is also the last channel to cut over (`docs/MERGE-PLAN.md`); this is its first live run in this repository.

| ID | Case | Pre | Owner action | Expected in Many | Expected in SaaS | Look | Result |
|---|---|---|---|---|---|---|---|
| I1 | Inbound, delegation OFF | Test account connected, delegation off, Many AI off | Send a direct message to the test account from a tester | Lead (IGSID as external id) and inbound message stored | Nothing | Many Leads, Messages, logs | |
| I2 | Bot answer, delegation OFF | Many AI on for the account for this case | Send a message | Many AI answers once (the existing keyword/comment automation is a separate path; do not test comments here) | Nothing | Instagram app; Many Messages | |
| I3 | Delegation ON: inbound and bot answer | Canary setup order done for the account | Send a message | Forward succeeds | One inbound, one bot answer, no Many AI answer | Instagram app; SaaS inbox; delegation page | |
| I4 | Human reply | I3 passed | Handoff in SaaS; send another message; send one agent reply from the SaaS inbox | Accepted, then `sent`. Instagram text limit is 1000 bytes in the outbound code; keep the test reply short | Bot stops; agent reply shown. **UNVERIFIED:** delivery status for Instagram | Instagram app; SaaS inbox | |
| I5 | Take Over guard | I3 passed | As W5 on the Instagram conversation | 409 `CHANNEL_MANAGED_BY_SAAS` | none | Many conversation page | |
| I6 | Opt-out | Delegation off, then on | Send `STOP` | **UNVERIFIED:** no Instagram opt-out handling found; record what happened | Record | Instagram app; both inboxes | |
| I7 | Erasure via SaaS flow | I3 passed; staff claim for this Instagram account done (`POST /api/v1/platform/tenants/{id}/many-channel-claims`, because Many's Instagram account list names no workspace); link sync done; flag and window as W8 | As W8 for the Instagram person (IGSID) | `local_status: erased`. The erasure runbook states live Instagram handlers do not take part in an erasure lock, so pause the connection and quiesce workers first | Link `erased`; case `complete` or `needs_action` | As W8 | |
| I8 | Delegation off again | I3 done | As W9 | Native behavior returns | No events | Delegation page | |

### 3.4 Cross-cutting

| ID | Case | Owner action | Expected | Look | Result |
|---|---|---|---|---|---|
| X1 | Delegation toggle on and off per channel is independent | Turn delegation on for WhatsApp only, send one message on each channel | Only WhatsApp is forwarded; Facebook and Instagram stay native | Delegation pages; SaaS inbox | |
| X2 | Provider-wide webhook health (known limit) | Observe SaaS health after any webhook failure | One failing Meta webhook marks every delegated channel `webhook_unhealthy`; check Many webhook processing first | SaaS channel pages | |
| X3 | Signed routes denied at the edge | From outside, request `/api/saas/health` on the Many host | Edge 403 with `X-Edge-Deny: 1` | `curl -i` output | |
| X4 | Duplicate webhook delivery | Do not replay by hand. Note any case where Meta redelivered | No duplicate message or reply | Many Messages | |

## 4. Triage template

| Case ID | Result | UTC time | Opaque ids | What was seen (sanitized) | Class (code bug / config / Meta test-number behavior / UNVERIFIED stays) | Owner decision |
|---|---|---|---|---|---|---|
| | | | | | | |

Label every result as a **test-number result**. Real numbers can behave differently (templates, quality rating); they are tested at cutover with a rollback (`docs/PHASE-6-PLAN.md` risks).
