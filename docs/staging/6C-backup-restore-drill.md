# 6C: Backup and restore drill

Status: **scripts written and syntax-checked; the Docker parts have NOT been run** (the build container has no Docker). The owner runs this on the staging server (backup) and on a clean machine (restore). Throwaway or staging data only. Exit criterion from `docs/MERGE-PLAN.md`: backup restored successfully on a clean machine; row counts and Alembic heads match.

## What exists

| File | Purpose |
|---|---|
| `scripts/ops/backup_all.sh` | Dumps both databases (`pg_dump -Fc`): Many Postgres 15 (service `pg15`) and SaaS Postgres 17 + pgvector (service `pg17`). Needs `--target DIR`, refuses without it. Writes `backup_<UTC>/` with two dumps, per-table row counts, Alembic versions, `MANIFEST.txt`, `SHA256SUMS`. Prints no secrets. |
| `scripts/ops/compare_counts.sql` | The one row-count query used on both sides (source at backup time, restored copy in the drill). |
| `scripts/ops/restore_drill.sh` | Starts its own throwaway compose project (name must start with `drill`, own containers and volumes, no published ports, random password never printed), restores both dumps, compares counts and Alembic heads, prints a result table, removes everything. Exit 0 pass, 1 mismatch, 2 setup error. |
| `scripts/ops/test_ops_compare.sh` | Offline test of the shell logic with a fake `docker` (does not test real Postgres). |

The existing `scripts/backup_postgres.sh` / `restore_postgres.sh` (Many only, `docs/backup-and-restore.md`) are unchanged.

## Before you start

- Same repository commit on both machines (the drill reads the Alembic heads from `backend/alembic/versions` and `modules/saas/apps/api/alembic/versions`).
- Staging host: the stack is up, `ENV_FILE` points at the host-only env file (compose needs it to parse the file; the script never reads or prints it).
- Clean machine: Docker with the compose plugin, `bash`, `python3`, `sha256sum`, the repository checked out, internet or a local registry to pull `postgres:15` and `pgvector/pgvector:pg17` (same images as `docker-compose.unified.yml`).
- Pause test traffic during the backup. Counts are taken right after the dump; a write in between shows up as a mismatch on a busy table. Re-run the backup in a quiet window if that happens.

## Steps

1. **Backup on staging** (record the start and end time):
   ```sh
   ENV_FILE=/path/to/host-only.env scripts/ops/backup_all.sh --target /var/backups/business-mind
   ```
   If your overlay is not the default, also set `COMPOSE_FILE` (for example `docker-compose.unified.yml:docker-compose.staging.yml`; use the real overlay file names from 6B). Expected last lines: `Backup complete: /var/backups/business-mind/backup_<UTC>`.
2. **Copy off the host** (any tool you trust, for example `scp` or `rsync`) to the clean machine. Note the size and copy time.
3. **Verify the copy** on the clean machine: `cd backup_<UTC> && sha256sum -c SHA256SUMS` (the drill also does this).
4. **Restore drill on the clean machine**:
   ```sh
   scripts/ops/restore_drill.sh --backup /path/to/backup_<UTC>
   ```
   It prints one row per table (`DB TABLE SOURCE RESTORED RESULT`), an Alembic table (source, restored, repo head), timings, and `RESULT: PASS` or `RESULT: FAIL`. Add `--keep` to leave the throwaway databases running for inspection (remove them afterwards with the command it prints). Use `--skip-repo-head` only when you restore an older backup on purpose; then run the migrations and check again.
5. **Optional manual spot check** (login and look at data): not part of the script; use `--keep`, never point a real app at the drill databases.
6. Fill the result template below and send it back.

Offline compare of two count files (no Docker): `scripts/ops/restore_drill.sh --compare-only counts_many.tsv restored_counts.tsv`.

## Timing table (owner fills in)

| Item | Start | End | Seconds / size | Notes |
|---|---|---|---|---|
| Backup both DBs on staging | | | | |
| Dump size many / saas | | | / | |
| Copy to clean machine | | | | |
| Image pull on clean machine | | | | |
| Restore many (pg15) | | | | printed by the drill |
| Restore saas (pg17) | | | | printed by the drill |
| Whole drill | | | | |

## Result template

```
Date (UTC):
Repository commit:
Staging host / clean machine:
Backup folder name:
sha256sum -c result:
Tables compared:
Row-count mismatches:
Alembic many: source / restored / repo head:
Alembic saas: source / restored / repo head:
RESULT line printed by the drill:
Anything unexpected (copy the exact output):
```

| Check | Result |
|---|---|
| Checksums verify | |
| Many row counts match | |
| SaaS row counts match | |
| Many Alembic head matches | |
| SaaS Alembic head matches | |
| Throwaway project removed (`docker compose ls` shows no `drill*`) | |

## Rollback and safety

- The drill never uses the running project, its volumes or its ports. If it aborts, remove leftovers: `docker compose ls`, then `docker compose -p <drillNAME> down -v` for any `drill*` project only.
- The backup script only reads the databases (`pg_dump`, read-only counts). A failed run removes its partial folder.
- Backups hold real or staging data: keep the folder mode 700 (the scripts set umask 077), copy over an encrypted channel, delete the clean-machine copy after the drill.
- If a restore fails, do not repair the live database. Report the exact output.

## Not covered

Redis (queue and cache; rebuildable), uploaded SaaS files in the `saas_data` volume (back this volume up separately; **UNVERIFIED** what it holds in staging), and point-in-time recovery.
