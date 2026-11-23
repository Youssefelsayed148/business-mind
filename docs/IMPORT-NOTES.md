# Import notes (Phase 1)

What was imported into this repository, with which commits, how name clashes were resolved,
and how to read the history. Source repositories were only read (local `git fetch`); they were
never modified.

## Sources

| | ManyOsirisChat (root of this repo) | Saas-Chatbot (`modules/saas/`) |
|---|---|---|
| Local source | `ManyOsirisChat`, branch `main` | `SAAS-chats-ai`, branch `main` (remote name `Saas-Chatbot`) |
| Original tip | `da3ed28edcb3ec19b3cb44fc8ddec343147d2f63` | `26d6b66c1880676194723bf5715cd1562d6926a8` |
| Tip in this repo | `da6c17efd00772b18fe770e136b17a5092879d6d` (rewritten, see below) | identical id, unchanged |
| Commits imported | 114 | 457 |
| Method | `git merge --allow-unrelated-histories` of the rewritten history | `git subtree add --prefix=modules/saas ... main` (no `--squash`) |
| Merge commit here | `4de94824192b122432efd0e01024472cdf686629` | `3d4fb78f86c38c872834fcd349c8bf108c256dec` |

Other commits made in Phase 1: `f832dae` (move SaaS CLAUDE.md/AGENTS.md to docs/legacy, pure renames),
`49b7c33` (merge-dev compose, env example, legacy README, commit map). Branch: `phase-1/foundation`.

Not imported: Many's untracked local `STATE.md`; the SaaS tag `phase-1-complete`
(`fde670f83c0f5e67e0ffe597a519f0ddd8d6c62b`, an ancestor of the imported tip), because the repo rules forbid tags;
Many's remote branch `feature/saas-delegation` (identical to `main` at import time: 0 commits ahead or behind).

Proof the SaaS code is untouched: `git rev-parse HEAD:modules/saas` equals the tree of the original
`26d6b66` (`a9b1bd58cd9fed1e7b311c5feab9175a5df45ed9`) at the time of the subtree import. The only later
change under `modules/saas/` is the removal of `CLAUDE.md` and `AGENTS.md` (moved to `docs/legacy/`).

## Credentials removed from Many's history (Many ids changed)

Two paths were found tracked in Many's history and were removed from **every** commit before import:

- `popeye access token.txt` (tracked at HEAD; also held a webhook secret and a verify token)
- `dashboard/.env.local` (in history from `f92dcfc` to `3199955`)

Tool: `git filter-branch --index-filter 'git rm --cached --ignore-unmatch -q -- "popeye access token.txt" dashboard/.env.local'`
on a throwaway clone, with a commit filter that records every `old new` pair
(`git-filter-repo` was the first choice but is blocked by this machine's Application Control policy).
`--prune-empty` cannot be combined with a custom commit filter, so the filter itself drops
single-parent commits whose tree did not change; result: **0 dropped, 114 of 114 rewritten**.

Because the root commit changed, **every Many commit id changed**. Old to new map:
`docs/legacy/many-commit-map.txt` (114 lines). Docs in both repos that cite Many commit ids
(for example "D5 `59d3442`") use the old ids. Check result: 39 distinct Many commits cited in Many's docs and
15 cited in the SaaS docs, all present in the map (0 unmapped, none keep their id).
Example: `59d3442ea5f0...` is now `70e61589003e...`; `da3ed28...` is now `da6c17ef...`.
SaaS ids are unchanged, so SaaS citations still resolve.

Proofs (run in the scratch clone and in this repo):

- `git log --all -- "popeye access token.txt" dashboard/.env.local` prints nothing.
- Old token blob `176db6acb1b52e1e226dc5da7bd69abb0f8caaca` and old `.env.local` blob
  `677ff901c9dd913bc001d9b79de5983583eb0db0`: `git cat-file -e` fails in this repo.
- `ls-tree -r` of original `da3ed28` vs rewritten tip differs by exactly one line: `popeye access token.txt`.
- `refs/original` deleted, reflog expired, `git gc --prune=now` run in the scratch clone; only the rewritten `main` was fetched here.

Owner actions (not part of Phase 1, no live system touched): revoke the Meta token; rotate the webhook
secret and verify token with the apps' settings in a planned window. See `docs/MERGE-PROGRESS.md`.

## Layout and name clashes

| Item | Resolution |
|---|---|
| `CLAUDE.md` | Root keeps this repo's bootstrap file (the only binding one). Many's -> `docs/legacy/many-CLAUDE.md`; SaaS's -> `docs/legacy/saas-CLAUDE.md` |
| `AGENTS.md` | Many has none. SaaS's -> `docs/legacy/saas-AGENTS.md`. `modules/saas/apps/web/AGENTS.md` stays |
| `docs/` | Many's docs live in root `docs/` (no file name collisions with the bootstrap docs); SaaS docs in `modules/saas/docs/` |
| `.github/` | Root keeps Many's `workflows/saas-delegation.yml`. SaaS workflows sit under `modules/saas/.github/` and are inactive (GitHub only reads the root). **The SaaS has no CI in this repository until Phase 2.** |
| `.gitignore`, `.gitattributes` | Root = Many's (one line added: `.env.merge-dev`). SaaS's stay nested in `modules/saas/` |
| Compose files | Many's `docker-compose*.yml` at root; SaaS `compose.yaml` / `compose.prod.yaml` in `modules/saas/`; new `docker-compose.merge-dev.yml` at root |
| `scripts/`, `README.md`, `Makefile`, `package.json` | No path clashes: SaaS copies are under `modules/saas/` |
| SaaS layout | **Kept as-is** under `modules/saas/apps/{api,web}`, `modules/saas/packages/widget` (decision: no re-layout in Phase 1). The worker is `modules/saas/apps/api/app/worker` (same image, `python -m app.worker`). No code or path edits |
| Stray tracked Many files | `*.patch`, `phase-*-prompt.md`, `celerybeat-schedule`, `dashboard/tsconfig.tsbuildinfo` imported unchanged (cleanup candidates, later phase) |

## Reading the history

- Many: `git log da6c17e` (114 commits) or normal `git log -- backend/...`.
- SaaS: commits keep their **original paths** (`apps/api/...`), because the subtree import does not rewrite history.
  Use `git log 26d6b66 -- apps/api/app/main.py` for file history; `git log -- modules/saas/...` shows only the import merge.
- Counts: `git rev-list --count da6c17e` = 114, `git rev-list --count 26d6b66` = 457.

## Secret scan

`gitleaks 8.30.1` (official release, SHA-256 checked against the published checksums) over this branch's history:
34 findings, all rule `generic-api-key`, all in Many's `docs/saas-delegation/*-evidence/` runner scripts and logs;
by shape they are fake test fixtures (`JWT_SECRET`/`META_APP_SECRET` values of hyphen-separated lowercase words,
and 36-character UUID `token_id`s). Nothing in the token file, `.env.local`, or the SaaS tree. They are listed here
for transparency, not allow-listed in any config. A separate, earlier regex/filename scan of every blob in both source
histories found nothing else that looked real.
