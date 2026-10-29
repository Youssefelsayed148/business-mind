# A5 local upgrade - 2026-10-28

Owner approved v26.0 after the explicit recommendation. Primary source:
https://github.com/facebook/facebook-nodejs-business-sdk/blob/main/src/api.js
(public raw source fetched successfully; VERSION returns v26.0, SDK 26.0.2).
This confirms Meta's SDK pin, not a compatibility guarantee for our endpoints.
Changelog/versions remain HTTP 429/inaccessible. No sunset date asserted.

Updated batch-b config, `.env.example`, `.env.production.example`, README,
WhatsApp implementation docs and review pack. Real env files were not read.
Added 32 mocked version-routing cases: default + shared config override,
Facebook/WhatsApp clients and OAuth, graph.instagram.com profile/media and
unversioned Instagram login/exchange/refresh endpoints. No Instagram handler
or messaging-client implementation changed; D5 untouched.

Audit: version-audit.json. All production clients use META_GRAPH_API_VERSION.
v99.0 values are synthetic tests and intentionally retained. The only v21.0
match was the stale batch-b plan, subsequently replaced with the updated
canonical plan; no current v21.0 production/doc default remains in audited
source. Earlier evidence/history is not rewritten. Templates were read only to
verify the approved default and were not copied into the test snapshot.

Fresh snapshot: source-manifest.json, base e284afd plus recorded reviewed
uncommitted files, no worker overlays or real env/token files. Tests ran in
env-cleared loopback-only netns with new Postgres 18 and Redis, then both stopped.
Explicit APP_ENV=test, TEST_DATABASE_URL and matching DATABASE_URL; host/name
printed, current_database and conftest target asserted. URL:
postgresql+psycopg://postgres@/many_test_closeout_a5?host=/var/tmp/many-closeout-a5-20261028-01/socket&port=55463.

prepare.py exit 0; run.sh exit 0; exact expanded pytest command in commands.log.
**237 passed, 0 failures/errors/skips, 5 warnings, 4.82 s** (tests.xml/tests.log).
No full suite repeated. Previous 911-pass full run predates these corrections;
full final integrated testing still pending. Live Meta/OpenAI/SaaS checks,
hosted CI, deployment and production env changes remain UNVERIFIED/not run.

R1 next: batch-b docs/saas-delegation/R1-DESIGN.md. No migration added; owner
approval and safe provider-namespace evidence/policy are required first.
