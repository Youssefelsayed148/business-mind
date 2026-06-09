#!/usr/bin/env sh
set -eu

ENV_FILE="${ENV_FILE:-.env}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
DB_SERVICE="${DB_SERVICE:-postgres}"
POSTGRES_USER="${POSTGRES_USER:-}"
POSTGRES_DB="${POSTGRES_DB:-}"
BACKUP_DIR="${BACKUP_DIR:-backups}"

env_value() {
  if [ -f "$ENV_FILE" ]; then
    awk -F= -v key="$1" '$1 == key { value = substr($0, length(key) + 2) } END { gsub(/^"|"$/, "", value); print value }' "$ENV_FILE"
  fi
}

POSTGRES_USER="${POSTGRES_USER:-$(env_value POSTGRES_USER)}"
POSTGRES_DB="${POSTGRES_DB:-$(env_value POSTGRES_DB)}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-postgres}"

mkdir -p "$BACKUP_DIR"
timestamp="$(date -u +"%Y%m%dT%H%M%SZ")"
backup_file="$BACKUP_DIR/postgres_${POSTGRES_DB}_${timestamp}.dump"

echo "Creating PostgreSQL backup from service '$DB_SERVICE' database '$POSTGRES_DB'..."
if docker compose -f "$COMPOSE_FILE" exec -T "$DB_SERVICE" \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > "$backup_file"; then
  echo "Backup created: $backup_file"
else
  rm -f "$backup_file"
  echo "Backup failed." >&2
  exit 1
fi
