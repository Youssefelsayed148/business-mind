# Rules for this repository (binding)

Merge of ManyOsirisChat (Many) and Saas-Chatbot (SaaS) into one platform.
Read docs/MERGE-PLAN.md and docs/MERGE-PROGRESS.md first.

1. Old repos are read-only references; never modify or push to them.
2. Never open, print or commit .env, tokens or secrets (incl. "popeye access token.txt").
   No live Meta tokens, webhooks or databases; no real Meta/OpenAI calls.
   Tests: throwaway DB only, APP_ENV=test and TEST_DATABASE_URL set explicitly, print host/name first.
3. Instagram receive/dispatch/send code is frozen. If a task needs an edit there, STOP and ask.
   Any approved edit: tiny, tested with the flag off, reversible.
4. Plan first, wait for OK, then act; do not re-ask each step after approval.
5. Reversible changes only; feature branches; draft PRs; no push to main, no force-push, no tags.
6. Never invent results; report exact commands and outcomes.
7. Update docs/MERGE-PROGRESS.md at the end of every session.
