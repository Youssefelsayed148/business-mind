#!/usr/bin/env bash
# Staging deploy: preflight, backup (when data exists), build, migrate, start, wait, outside checks.
#   scripts/staging/deploy.sh --backup-dir /var/backups/business-mind [--first-run]
# Needs the owner's approval to run (docs/staging/6B-staging-stack.md). Never touches a live system.
source "$(dirname "$0")/common.sh"
backup_dir=""; first_run=0
while [ $# -gt 0 ]; do case "$1" in
  --backup-dir) backup_dir="$2"; shift 2;;
  --first-run) first_run=1; shift;;
  *) die "unknown argument $1";; esac; done
[ -n "$backup_dir" ] || die "--backup-dir is required (a deploy always has a way back)"

scripts/staging/preflight.sh
echo "$(date -u +%FT%TZ) deploy of $(git rev-parse HEAD)" >> "$backup_dir/deploy.log" 2>/dev/null || { mkdir -p "$backup_dir" && echo "$(date -u +%FT%TZ) deploy of $(git rev-parse HEAD)" >> "$backup_dir/deploy.log"; }
if [ "$first_run" -eq 0 ]; then
  [ -x scripts/ops/backup_all.sh ] || die "scripts/ops/backup_all.sh missing"
  scripts/ops/backup_all.sh "$backup_dir/pre-deploy-$(date -u +%Y%m%dT%H%M%SZ)"
fi
"${COMPOSE[@]}" build
"${COMPOSE[@]}" up -d
echo "waiting for nginx to be healthy (up to 5 minutes)"
for _ in $(seq 1 60); do
  state=$("${COMPOSE[@]}" ps --format '{{.Service}} {{.Health}}' nginx 2>/dev/null | awk '{print $2}')
  [ "$state" = "healthy" ] && break; sleep 5
done
[ "$state" = "healthy" ] || { "${COMPOSE[@]}" ps; die "nginx not healthy: run rollback (scripts/staging/rollback.sh) or read the logs"; }
"${COMPOSE[@]}" ps
set -a; . "$ENV_FILE"; set +a
python3 scripts/staging/check_outside.py --many "$MANY_HOST" --saas-web "$SAAS_WEB_HOST" --saas-api "$SAAS_API_HOST"
echo "DEPLOY DONE. Next: Alembic heads (docs/staging/6B-staging-stack.md), then the 6E cases."
