# Backup and Restore

Backups protect ManyOsirisChat from accidental deletion, failed deployments, operator mistakes, and VPS disk loss. PostgreSQL logical backups are the primary backup method because they are portable across machines and Docker volume names.

## Local Backup

PowerShell:

```powershell
.\scripts\backup_postgres.ps1
```

Shell:

```sh
sh scripts/backup_postgres.sh
```

Backups are written to `backups/` as timestamped custom-format dump files, for example:

```text
backups/postgres_manyosiris_20260521T120000Z.dump
```

## Local Restore

PowerShell:

```powershell
.\scripts\restore_postgres.ps1 -Backup backups\postgres_manyosiris_20260521T120000Z.dump
```

Shell:

```sh
sh scripts/restore_postgres.sh backups/postgres_manyosiris_20260521T120000Z.dump
```

Restore asks for confirmation before overwriting database objects. Use `-Force` in PowerShell or `--force` in shell only for automation after you have rehearsed restores.

## VPS Backup

Use the same scripts with deployment-specific environment values:

```sh
ENV_FILE=.env.production COMPOSE_FILE=docker-compose.prod.yml DB_SERVICE=postgres BACKUP_DIR=/var/backups/manyosirischat sh scripts/backup_postgres.sh
```

PowerShell can use equivalent parameters:

```powershell
.\scripts\backup_postgres.ps1 -EnvFile .env.production -ComposeFile docker-compose.prod.yml -DbService postgres -BackupDir backups
```

## Configuration

Scripts read these values from environment variables first, then from `ENV_FILE`, then defaults:

- `ENV_FILE`, default `.env`
- `COMPOSE_FILE`, default `docker-compose.yml`
- `DB_SERVICE`, default `postgres`
- `POSTGRES_USER`, default `postgres`
- `POSTGRES_DB`, default `postgres`
- `BACKUP_DIR`, default `backups`

## Suggested Schedule

- Run one backup daily.
- Keep 7 daily backups.
- Keep 4 weekly backups.
- Copy VPS backups off the VPS to object storage or another host.

## Restore Rehearsal

1. Create a fresh backup.
2. Start a disposable local database or staging VPS.
3. Restore the backup there.
4. Run migrations if needed.
5. Log in and confirm campaigns, accounts, leads, messages, and logs are present.

Do not trust backups until you have successfully restored one.

## Optional Docker Volume Snapshot

Logical PostgreSQL backups are the primary backup. Docker volume backups can be useful for full local snapshots, but they are more environment-specific and should not replace `pg_dump -Fc` backups.
