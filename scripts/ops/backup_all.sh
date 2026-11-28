#!/usr/bin/env bash
# backup_all.sh - back up BOTH databases of the unified platform (Phase 6C).
#   Many  : Postgres 15, compose service pg15 (user/db many by default)
#   SaaS  : Postgres 17 + pgvector, compose service pg17 (user/db saas by default)
# Writes TARGET/backup_<UTC timestamp>/ with: many_<ts>.dump, saas_<ts>.dump (pg_dump -Fc),
# counts_many.tsv, counts_saas.tsv, alembic_*.txt, MANIFEST.txt and SHA256SUMS.
# Never prints secrets: it connects through the container's local socket and uses no password.
#
# Usage:  scripts/ops/backup_all.sh --target /var/backups/business-mind
# Env (all optional):
#   ENV_FILE        compose --env-file (host-only secrets file); never read or printed by this script
#   COMPOSE_FILE    compose file(s), docker compose syntax (default: -f docker-compose.unified.yml)
#   COMPOSE_PROJECT_NAME  compose project of the RUNNING stack
#   MANY_SERVICE=pg15 MANY_DB_USER=many MANY_DB_NAME=many
#   SAAS_SERVICE=pg17 SAAS_DB_USER=saas SAAS_DB_NAME=saas
# Exit: 0 ok, 1 backup failed, 2 usage error.
# Status: written and syntax-checked. NOT RUN against real databases (no Docker in the build container).
set -euo pipefail
umask 077

usage() { echo "Usage: $0 --target DIR   (DIR is required; a backup_<timestamp> folder is created inside it)" >&2; exit 2; }

TARGET=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --target) [ "$#" -ge 2 ] || usage; TARGET="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "Unknown argument: $1" >&2; usage ;;
  esac
done
if [ -z "$TARGET" ]; then
  echo "Refusing to run: --target DIR is required." >&2
  usage
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SQL="$HERE/compare_counts.sql"
[ -f "$SQL" ] || { echo "Missing $SQL" >&2; exit 2; }

MANY_SERVICE="${MANY_SERVICE:-pg15}"; MANY_DB_USER="${MANY_DB_USER:-many}"; MANY_DB_NAME="${MANY_DB_NAME:-many}"
SAAS_SERVICE="${SAAS_SERVICE:-pg17}"; SAAS_DB_USER="${SAAS_DB_USER:-saas}"; SAAS_DB_NAME="${SAAS_DB_NAME:-saas}"

COMPOSE=(docker compose)
if [ -n "${ENV_FILE:-}" ]; then COMPOSE+=(--env-file "$ENV_FILE"); fi
if [ -z "${COMPOSE_FILE:-}" ]; then COMPOSE+=(-f docker-compose.unified.yml); fi
TAB="$(printf '\t')"

TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$TARGET/backup_$TS"
if [ -e "$OUT" ]; then echo "Refusing: $OUT already exists." >&2; exit 2; fi
mkdir -p "$TARGET"
mkdir "$OUT"
DONE=0
cleanup() {
  if [ "$DONE" -ne 1 ]; then rm -rf "$OUT"; echo "Backup failed; partial folder removed." >&2; fi
}
trap cleanup EXIT

backup_one() { # label service user db
  local label="$1" svc="$2" user="$3" db="$4"
  local dump="$OUT/${label}_${TS}.dump"
  echo "[$label] dumping database '$db' from service '$svc' ..."
  "${COMPOSE[@]}" exec -T "$svc" pg_dump -U "$user" -d "$db" -Fc > "$dump"
  [ -s "$dump" ] || { echo "[$label] dump is empty" >&2; return 1; }
  # Integrity: the archive table of contents must be readable by pg_restore.
  "${COMPOSE[@]}" exec -T "$svc" pg_restore -l < "$dump" > /dev/null \
    || { echo "[$label] pg_restore -l could not read the dump" >&2; return 1; }
  "${COMPOSE[@]}" exec -T "$svc" psql -X -At -F "$TAB" -v ON_ERROR_STOP=1 -U "$user" -d "$db" < "$SQL" > "$OUT/counts_${label}.tsv"
  "${COMPOSE[@]}" exec -T "$svc" psql -X -At -U "$user" -d "$db" -c "SELECT version_num FROM alembic_version" > "$OUT/alembic_${label}.txt"
  [ -s "$OUT/alembic_${label}.txt" ] || { echo "[$label] no alembic version found" >&2; return 1; }
  echo "[$label] ok: $(wc -c < "$dump") bytes, $(wc -l < "$OUT/counts_${label}.tsv") tables, alembic $(tr -d '\n' < "$OUT/alembic_${label}.txt")"
}

backup_one many "$MANY_SERVICE" "$MANY_DB_USER" "$MANY_DB_NAME"
backup_one saas "$SAAS_SERVICE" "$SAAS_DB_USER" "$SAAS_DB_NAME"

{
  echo "backup_utc=$TS"
  echo "many_service=$MANY_SERVICE db=$MANY_DB_NAME alembic=$(tr -d '\n' < "$OUT/alembic_many.txt")"
  echo "saas_service=$SAAS_SERVICE db=$SAAS_DB_NAME alembic=$(tr -d '\n' < "$OUT/alembic_saas.txt")"
  echo "git_commit=$(git -C "$HERE" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  echo "note=counts are taken right after the dump; writes in between can differ on busy tables. Back up in a quiet window for an exact drill."
} > "$OUT/MANIFEST.txt"

( cd "$OUT" && sha256sum -- *.dump *.tsv *.txt > SHA256SUMS && sha256sum -c SHA256SUMS > /dev/null )
DONE=1
echo "Backup complete: $OUT"
echo "Next: copy it off this host, then run scripts/ops/restore_drill.sh --backup $OUT on a clean machine."
