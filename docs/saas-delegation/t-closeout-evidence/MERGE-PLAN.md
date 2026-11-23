# Many integration plan - approval required

Verified starting refs:

- Target `feature/saas-delegation`: db12511754862b7d1a05a8b5ac6ad459045b6a36.
- Application `closeout/batch-b`: e284afd2d8866dd75c551404306e23c015d8c7cc.
- Merge base: 51c0d621d87ce051e5f5b7907bfe8c0836b921f5.
- Target-only committed work is db12511 documentation/tooling; batch-b also has
  the four uncommitted Batch T corrections listed in reviewed-fix-manifest.json.
- 59d3442 is already an ancestor of batch-b and remains unchanged; D5 OPEN.

Pending sequence (commands are a plan, NONE executed):

1. Resolve A5 with the owner, finish the ordered work and the separate R1
   migration-design approval, run related checks, then run the final integrated
   full suites once. Record final source SHA and any worktree diff.
2. Commit reviewed implementation changes in batch-b and lead evidence/docs
   in the target checkout with explicit file lists; exclude env/token files,
   snapshots, node_modules and generated artifacts. Recheck both statuses.
3. Inspect `git log --left-right --oneline feature/saas-delegation...closeout/batch-b`
   and `git diff --name-only feature/saas-delegation...closeout/batch-b`; report
   both final full SHAs and anticipated documentation conflicts. Obtain explicit
   approval for the target feature-branch merge.
4. Only after approval, in the original target checkout run
   `git merge --no-ff --no-commit closeout/batch-b`. Preserve the latest
   PROGRESS/CLOSEOUT-PLAN/handoff evidence in documentation conflicts; review
   the application diff and confirm D5 unchanged. If resolution introduces new
   behavior, run affected tests; repeat a full suite only with a stated reason.
5. Keep the two external plan copies byte-identical; contract files/manifests
   stay unchanged unless a separately approved contract change requires them.
   Run contract-copy checks and `git diff --check`, inspect the staged result,
   then create the local merge commit and report its exact SHA/results.

Do not merge to main, push, deploy, or perform live provider/SaaS actions.
Report D5 as an independent open release gate when requesting the feature merge.
