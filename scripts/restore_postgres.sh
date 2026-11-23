#!/usr/bin/env sh
set -eu

ENV_FILE="${ENV_FILE:-.env}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
DB_SERVICE="${DB_SERVICE:-postgres}"
POSTGRES_USER="${POSTGRES_USER:-}"
POSTGRES_DB="${POSTGRES_DB:-}"
FORCE="false"
BACKUP_FILE=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --force|-f)
      FORCE="true"
      ;;
    *)
      BACKUP_FILE="$1"
      ;;
  esac
  shift
done

if [ -z "$BACKUP_FILE" ]; then
  echo "Usage: scripts/restore_postgres.sh [--force] backups/file.dump" >&2
  exit 1
fi

if [ ! -f "$BACKUP_FILE" ]; then
  echo "Backup file not found: $BACKUP_FILE" >&2
  exit 1
fi

env_value() {
  if [ -f "$ENV_FILE" ]; then
    awk -F= -v key="$1" '$1 == key { value = substr($0, length(key) + 2) } END { gsub(/^"|"$/, "", value); print value }' "$ENV_FILE"
  fi
}

POSTGRES_USER="${POSTGRES_USER:-$(env_value POSTGRES_USER)}"
POSTGRES_DB="${POSTGRES_DB:-$(env_value POSTGRES_DB)}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-postgres}"

if [ "$FORCE" != "true" ]; then
  echo "This will overwrite objects in database '$POSTGRES_DB' using '$BACKUP_FILE'."
  printf "Type RESTORE to continue: "
  read confirmation
  if [ "$confirmation" != "RESTORE" ]; then
    echo "Restore cancelled."
    exit 1
  fi
fi

echo "Restoring PostgreSQL backup into service '$DB_SERVICE' database '$POSTGRES_DB'..."
if docker compose -f "$COMPOSE_FILE" exec -T "$DB_SERVICE" \
  pg_restore --clean --if-exists --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB" < "$BACKUP_FILE"; then
  echo "Restore completed."
else
  echo "Restore failed." >&2
  exit 1
fi
