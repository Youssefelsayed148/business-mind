#!/usr/bin/env bash
# Staging rollback: stop the stack; with --restore, restore both databases from a backup folder.
#   scripts/staging/rollback.sh                      stop the stack (keeps volumes and data)
#   scripts/staging/rollback.sh --restore <backup>   stop, then restore both databases (asks to type YES)
source "$(dirname "$0")/common.sh"
restore=""
[ "${1:-}" = "--restore" ] && restore="${2:-}"
"${COMPOSE[@]}" down --remove-orphans
echo "stack stopped; volumes kept."
if [ -n "$restore" ]; then
  [ -d "$restore" ] || die "backup folder $restore not found"
  read -r -p "Restore BOTH staging databases from $restore (this replaces staging data). Type YES: " answer
  [ "$answer" = "YES" ] || die "not confirmed, nothing restored"
  [ -x scripts/ops/restore_drill.sh ] || die "scripts/ops/restore_drill.sh missing"
  echo "Restore into the staging volumes is a manual step: see docs/staging/6C-backup-restore-drill.md ('restore into staging')."
fi
echo "DNS: staging has no live traffic; if you pointed a test webhook URL here, point it back in the Meta app."
