# R17 / B4 local documentation evidence - 2026-10-28

R1 was committed first as `f3a7de0`. Only documentation and the two policy pages
were changed for this ticket. No AI behavior, native dispatch or send handler changed.

Files: `docs/meta-app-review-submission.md`,
`dashboard/app/(auth)/privacy/page.tsx`, `dashboard/app/(auth)/terms/page.tsx`,
this report, and ticket-only additions to `PROGRESS.md` / `CLOSEOUT-PLAN.md`.
The separately authorized external SaaS plan file is synchronized byte-for-byte.

The review pack describes Many's Meta token/webhook ownership, the SaaS processor
and signed contract, R1 encrypted provider proof and unresolved operator cases,
callback/status behavior, two-phase account erasure, A16 acceptance versus verified
completion, retention exceptions and operator cleanup. Its nine permission rows
separate native Many evidence from the delegated step; every recording is UNVERIFIED.
It contains no reference to the unused engagement-management permission.

Both policies disclose business-support AI replies, processor copies, deletion
verification and actual retention boundaries. The human-agent tag is not used.
The 24-hour rule includes the existing WhatsApp valid free-entry-window exception:
`saas_outbound._window_open` and `test_whatsapp_free_entry_window_counts_as_open`
prove that exception exists. Outside the applicable window, local guards block
and make no Meta send. No strict-24-hour claim or automatic per-message AI label
was invented. This is documentation of existing behavior, not new enforcement.

## Checks and exact commands

From batch-b, copied only the two changed `.tsx` files into the existing env-free
dashboard snapshot. Cached Node/dependencies only; no network or application startup.

```text
wsl -d Ubuntu -u root -- unshare --net bash '/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/.closeout-worktrees/batch-b/.r1-validation/policy.sh'
```

Expanded check commands inside `source/dashboard`:

```sh
node node_modules/typescript/bin/tsc --noEmit --incremental false
NEXT_TELEMETRY_DISABLED=1 node node_modules/next/dist/bin/next lint --file 'app/(auth)/privacy/page.tsx' --file 'app/(auth)/terms/page.tsx'
```

Both exited 0; no TypeScript errors or changed-page ESLint warnings/errors.
`git diff --check -- docs/meta-app-review-submission.md 'dashboard/app/(auth)/privacy/page.tsx' 'dashboard/app/(auth)/terms/page.tsx'`
exited 0. Stdlib `python -` source assertions passed: nine UNVERIFIED permission
rows, R1 commit reference, unresolved operator wording, window/free-entry/tag
wording, marked owner inputs, no guessed privacy/legal emails or effective date.
Backend tests were not rerun for this documentation-only ticket; existing source
and R1 evidence are cited, without claiming a new backend or live result.

## Owner inputs / limits

Supply verified Meta app IDs/display name, legal operator name/address, privacy
and legal contacts, public policy/support/API URLs, approved effective date,
subprocessor list/locations/safeguards, retention/backup schedule and exceptions,
deletion response target/delay process, and commercial/legal terms. Policies are
drafts pending owner publication review. The existing backend status-page contact
also needs owner verification; this docs-only ticket does not change that endpoint.

Actual dashboard grants/eligibility, Business Verification/Tech Provider status,
public HTTPS callbacks, staging A16 completion, customer-facing AI disclosure in
recordings, native permission activity, D4 recordings, full suites, deployment
and submission are UNVERIFIED. No live/authenticated/paid call, publication,
push, merge or deploy was made. D5 remains confirmed; 59d3442 is unchanged.
