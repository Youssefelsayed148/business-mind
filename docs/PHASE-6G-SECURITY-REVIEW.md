# Phase 6G: security review of the merged surface

Status: **review done 2026-11-28 by reading code (a read-only reviewer subagent; I checked the findings I acted on against the files). Nothing was run against a live system.** Covers: SSO exchange, the Many proxy, the Phase 5 link, erasure and combined-audit code, the edge, compose and scripts, dependencies. Known items excluded: Phase 3 review items 1 to 11 (see `docs/PHASE-6G-FIXES.md`), the public repository, unpinned Many requirements. Result: **no critical or high finding in the code reviewed; 13 findings (0 critical, 0 high, 4 medium, 8 low, 1 info) plus the dependency audit below.**

## Findings and status

| ID | Sev | Where | What | Status |
|---|---|---|---|---|
| G-01 | medium | `linking/erasure.py` | A retry after a crash between the erase commit and the case update, or two simultaneous retries, could insert the same erase event twice (500, case stuck) | **Fixed** (looks up the event first; locks the case row). Test: `tests/test_phase6g_review.py` |
| G-02 | medium | `linking/erasure.py` | If no channel connection matched, the link was marked erased though no SaaS data was erased | **Fixed** (case goes to `needs_action: connection_missing`, link stays). Test added |
| G-03 | medium (low while staff-only) | `linking/audit_view.py` | Many's free-text audit `message` (can hold an email) was relayed to staff, against the "no personal data" promise | **Fixed** (staff see the event type only). Test added |
| G-04 | low | `linking/erasure.py` | A staff-set `many_channel_ref` containing `/`, `..`, `?` could change the Many path | **Fixed** in the erasure path (`channel_ref_invalid`). Proxy `forward()` itself and write-time validation of the reference are **open** (owner decision: validate on write) |
| G-05 | low | `customer_links.external_id` | Raw id kept until Many confirms; a case stuck in `needs_action` keeps it indefinitely | **Open, accepted trade-off** (design section 14). Mitigation to decide: an expiry job for stuck cases, or column encryption |
| G-06 | low | proxy token cache | Any Many 401 clears the whole token cache; the proxy has no per-request rate limit | **Open** (low); fix: drop only the failing key, add a per-user proxy limit |
| G-07 | low (design) | `identity/sso.py`, `sso_assertion.py` | The `mfa` claim means "user enrolled", not "this session passed MFA" | **Open, needs owner decision** (carry a session-level flag); matters when `SSO_REQUIRE_MFA_FOR_ADMIN` is turned on |
| G-08 | low | `nginx/unified.conf` Many host | `X-Forwarded-For` appended the client's value | **Fixed** (`$remote_addr`, like the SaaS hosts); static test now covers all three hosts |
| G-09 | low | `nginx/unified.conf` SaaS hosts | No `X-Content-Type-Options` or `Referrer-Policy` at the edge | **Partly fixed** (both added). `X-Frame-Options`, CSP and HSTS `includeSubDomains` left out on purpose (the widget may need framing); to confirm in staging |
| G-10 | low | edge default host | Unknown Host or SNI reached the Many dashboard | **Fixed for HTTPS** (`ssl_reject_handshake` default server). Port 80 default stays the redirect server; the dev default stays Many because the e2e driver relies on it (not changed, not run) |
| G-11 | low | `scripts/tls/make_internal_pki.sh` | Key files 644 and the folder mode left to the caller | **Fixed to the extent possible** (folder set to 755 explicitly; containers must enter it). The keys stay world-readable on the host: protect the parent folder (owner-only). Documented in 6A |
| G-12 | medium (staging) | compose | One env file for every container; Redis has no password (holds the SSO replay keys) on a shared network | **Open.** Fix before production: `requirepass` plus per-service env. Accepted for the first staging run only if staging holds no real data; owner to confirm |
| G-13 | info | compose | Image tags, not digests | **Open**; pin digests in the staging overlay before the soak |

## Checked and fine (reviewer, by reading)
Assertion verification (algorithm pinned, required claims, 60 s lifetime, one-use jti in Redis, fails closed); flag-off behaviour of SSO and the proxy; return-URL allowlist; membership takeover keyed on the SSO subject, never email; the mint path re-reads everything from the database; the proxy forwards only content-type and accept, never cookies, and builds paths only from the allowlist; per-call membership and permission checks; tenant isolation on every link and case query with uniform 404; no external id or name in responses or audit rows; erasure idempotent by request id; edge deny rules for every spelling checked by reading (live check is `check_outside.py` on staging); TLS settings; no secret values in the scripts.

Not verified by the reviewer: Next rewrites, HTTP/2 pseudo-header handling on a real nginx, the dashboard callback's state check (no callback code exists yet), `scripts/ops/`, Dockerfile `FROM` lines.

## Dependency audit (`npm audit --omit=dev`, 2026-11-28, registry reachable)
| App | Result | Action |
|---|---|---|
| SaaS web (Next 16.4.3) | 1 moderate (7 Next advisories) | Fixed by 16.4.6: upgrade is a separate commit with the full web gates (decision D9) |
| Many dashboard (Next 14.2.23) | 4: critical `next`, high `postcss`, `nanoid`, `source-map-js`. Even the last 14.x release (14.2.35) still reports critical next and high postcss; a clean audit needs Next 16.4.6 (a major jump). The dashboard uses `next/image` (logo), so the image route exists | **Owner decision**: major upgrade, or keep the old dashboard off the public edge and retire it in Phase 8 |
| Python | not run (no `pip-audit` here) | run `pip-audit` in the Many and SaaS images on staging; Many requirements are unpinned |

## Change log
- 2026-11-28, Claude Code: review by a read-only subagent; fixes G-01 to G-04, G-08 to G-11 written; SaaS tests run after the other agent finished (numbers in `docs/PHASE-6-REPORT.md` once recorded).
