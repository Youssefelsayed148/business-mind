# docs/legacy: files moved out of the way

These files came from the two source repositories. They are kept for reference only and are
**not binding**. The only binding rules for this repository are the root `CLAUDE.md`
(see also `docs/MERGE-PLAN.md`).

| File here | Original location | Why it moved |
|---|---|---|
| `many-CLAUDE.md` | `CLAUDE.md` in ManyOsirisChat (repo root) | Name clash with this repo's root `CLAUDE.md` (which is kept). Preserved from the merge parent. |
| `saas-CLAUDE.md` | `CLAUDE.md` in Saas-Chatbot, now at `modules/saas/` | Same clash. Moved with `git mv` (rename, no content change). |
| `saas-AGENTS.md` | `AGENTS.md` in Saas-Chatbot, now at `modules/saas/` | Agent rules of the old repo; superseded by the root `CLAUDE.md`. Moved with `git mv`. |
| `many-commit-map.txt` | n/a (generated) | Old to new commit ids for ManyOsirisChat, because two credential files were removed from its history before import. Docs in both repos cite old ids; look them up here. |

Not moved (left in place because they sit next to the code they describe): `modules/saas/apps/web/AGENTS.md`.

Note for readers of the moved files: paths and instructions inside them refer to the old
repositories' layouts and may be wrong here. For example, "migration head says 0022" in Many's
`CLAUDE.md` is a known stale note (the real head is 0030; see `docs/MERGE-PLAN.md`).
