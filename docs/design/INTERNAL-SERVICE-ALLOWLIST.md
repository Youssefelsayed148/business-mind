# Internal channel service allowlist — design only

2026-11-23, Codex. Status: **PROPOSED; NOT IMPLEMENTED; owner approval required**.

The exact proposed application/test diff is `internal-service-allowlist.proposed.patch`.
It is a review artifact, not an applied change. No workflow files are included.

## Policy

One process environment setting on both sides: `CHANNEL_INTERNAL_ALLOWED_HOSTS`.
Default is the empty string. Empty selects the existing validators without changing
their behavior, including Many's pre-existing development/test local-host allowance.
An empty list does not newly prohibit IP literals that legacy code already permits.

When non-empty, parse once at process module initialization, fail startup on invalid
entries, and emit a WARNING startup line containing the sorted hostnames only.
No tokens, URLs with credentials, or other environment values are logged. Changing
the setting requires restarting the API and worker processes.

The list is comma-separated, with canonical lowercase ASCII DNS names only. Each
label starts with a letter and contains letters, digits or interior hyphens; DNS
length limits apply. Reject empty entries, duplicates, whitespace, wildcards,
leading/trailing dots, IP literals, numeric host encodings, userinfo, ports,
URLs, localhost and reserved local-name suffixes in this configuration.

With the policy enabled, URL validation is deliberately strict: reject controls,
whitespace, Unicode hostnames, percent escapes in the authority, backslashes,
userinfo (including an empty username), query strings, fragments and invalid ports.
Reject uppercase and trailing-dot hostname spellings; do not canonicalize those
spellings into an allowlist grant. Parse the authority, never search the URL text
for a permitted hostname. All URL IP literals are rejected under the enabled policy.

Unlisted DNS hostnames must resolve entirely to global unicast addresses. Listed
hostnames may additionally resolve to RFC1918 IPv4 or IPv6 ULA addresses only.
Loopback, link-local/metadata, multicast, reserved/documentation, unspecified and
IPv4-mapped private IPv6 addresses remain forbidden. Empty DNS answers or one
forbidden address in a mixed answer reject the entire target. DNS failure rejects
the request; there is no fallback that skips validation.

This opt-in policy applies in every environment when non-empty. Production retains
the existing HTTPS requirement even for listed hosts. Development/test may use HTTP
on the isolated compose network. HMAC signing and verification remain unchanged.

## Integration and exact edit boundary

Two byte-identical, dependency-free policy modules are proposed, one inside each
application package. This avoids cross-package imports or dependency changes and
keeps both existing images self-contained. Before merging, compare the two source
files byte-for-byte and run the same policy cases in both application environments.

Existing code edits are restricted to imports and these shared validation helpers:

- Many `saas_delegation_service.validate_base_url`: opt-in branch validates syntax,
  production HTTPS, DNS answers and the shared address policy; empty uses old code.
- SaaS `router._validate_base_url`: opt-in syntax/HTTPS branch; empty uses old code.
- SaaS `outbound.resolve_target`: apply the shared address policy; retain existing
  single-resolution IP pinning, original Host/TLS SNI and certificate verification.

There are zero edits to Instagram receive/dispatch/send implementations, callers,
models, feature flags, contract text, HTTP transports or signing. There are no
settings-model or main/startup call-site changes: importing the policy initializes
and logs it once in each importing process. Invalid configuration fails import.

Both existing HTTP client factories disable redirect following. The proposal keeps
that behavior: reject/fail the redirect response through existing delivery logic,
never issue a request to Location, even when Location is another listed host.
Tests exercise the real client factories with a mock HTTP transport and assert
that only the first URL was requested. No live hosts are contacted.

## Production variant

Keep the union to exactly two service names, with only one outbound target granted
per application: Many API/workers get `saas-api`; SaaS API/worker get `many-api`.
Do not give every container both entries. No nginx hostname is allowlisted.

Data on fake channel rows uses `http://saas-api:8000` and `http://many-api:8000`
for local testing. Production must instead use HTTPS endpoints addressed by those
service names, with certificates containing the matching SANs and a trusted CA.
Internal TLS termination/listeners and certificate provisioning belong in the
production compose/deploy outline; do not weaken HTTPS or disable verification.
No production deployment or real certificates are used during this phase.

Runtime containers must explicitly have empty HTTP_PROXY/HTTPS_PROXY/ALL_PROXY
and local-only networking. Many's existing client honors proxy environment settings;
this patch does not change that client. Do not allow inherited proxy configuration
to reroute signed traffic. Build-time dependency access is separate from runtime.

## DNS limitation requiring a decision

Many currently resolves in its validator, then httpx resolves again during send.
The patch preserves that transport. It does NOT provide address pinning or prevent
DNS rebinding between validation and connect. SaaS already pins its resolved IP.
Changing Many's HTTP transport/callers would exceed the approved helper-only scope.

The proposed scope therefore relies on owner-controlled compose DNS, service names,
network membership and proxy environment. The list is deployment configuration,
never tenant-supplied data. A network/DNS administrator able to change these service
records is inside that trust boundary. Public-host DNS rebinding remains a pre-existing
Many limitation; do not claim it is fixed or approve this design as full SSRF parity.
Owner must accept this explicit boundary for Phase 2, or authorize a separate design
for Many transport pinning. No such transport change is included in this patch.

## Proposed tests and execution gates

The patch includes exact new pytest files for both sides, covering:

- Both exact listed hosts resolving to private IPv4/ULA addresses.
- Unlisted private hosts and prefix/suffix impersonations.
- Uppercase/trailing-dot variants, all numeric/IP literals, userinfo, escapes,
  backslashes, whitespace, queries and fragments.
- Special ranges, empty answers and mixed allowed/forbidden DNS answers.
- Invalid/duplicate configuration, startup failure, non-empty startup warning,
  and no warning for the empty setting.
- Production HTTPS, public unicast DNS behavior, and legacy helper integration
  with an empty setting.
- Integration with both existing validators and retained SaaS IP pinning.
- Both unchanged HTTP client factories refusing a redirect to an unlisted host.

Before implementation approval, checks are syntax parsing of proposed Python,
`git apply --check` and patch path review only. No proposed tests have run.

After approval, first rerun the complete existing Many suite with the setting empty
(baseline 1007 passed / 0 failed / 0 skipped), separately from the new test file.
Run the complete existing SaaS suite once with the corrected socket environment
and the setting empty (Phase 1b was 1215 passed / 1 environment failure; that test
passed separately, so 1216 passing is an expectation, NOT an observed result).
Run the new test files separately with fake DNS/HTTP boundaries. Counts including
new tests naturally exceed the old baselines. Do not skip or alter old tests.

Use WSL2 and newly created throwaway Docker services only; APP_ENV=test,
ENVIRONMENT=test, explicit TEST_DATABASE_URL, and print the DB host/name before
each run. SaaS PGHOST must be `/var/tmp/saas-<session>/sock` with PGPORT matching
the socket; Many retains its required disposable `many_test_r1` database name.
Set REPO_IMPL_DIR outside the checkout so evaluation tests do not dirty tracked
reports. External test egress must be blocked, with fake credentials only.

Then prove the six compose e2e cases (three channels, delegation ON/OFF as fake
row data), logging both signed HTTP destinations by service name. OFF must produce
zero SaaS deliveries; ON must reach the mocked Meta boundary through both apps.
Run both contract-copy checks. Compare the final diff with base `8450ae5` to prove
zero frozen-code/call-site changes. Perform the requested `/security-review` after
implementation and record actual findings and limitations; it has not run yet.

## Design-session results

- Proposal generated only as a patch under docs; all seven proposed Python targets
  passed AST syntax parsing. `git apply --check` exited 0 without applying it.
- Application-path working-tree diff is empty. Only documentation/proposal files changed.
- `docker info --format '{{.ServerVersion}}'` failed on all three checks: Docker Desktop Linux
  engine pipe was absent. No containers, volumes, databases or tests were started.
- Implementation and workflow review gates remain pending.
