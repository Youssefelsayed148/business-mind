#!/bin/bash
set -euo pipefail
evidence='/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/docs/saas-delegation/t-closeout-evidence'
export PATH="/var/tmp/saas-closeout-tools/node-v24.22.1-linux-x64/bin:/usr/bin:/bin"
export NEXT_TELEMETRY_DISABLED=1 CI=1 APP_ENV=test
cd /var/tmp/many-closeout-t-20261028-02/source/dashboard
check() {
    local label="$1"; shift
    printf '%q ' "$@" >>"$evidence/dashboard-commands.log"
    printf '\n' >>"$evidence/dashboard-commands.log"
    local start=$SECONDS
    set +e
    "$@" >"$evidence/$label.log" 2>&1
    local status=$?
    set -e
    printf '%s exit=%s duration=%ss\n' "$label" "$status" "$((SECONDS-start))" | tee -a "$evidence/dashboard-commands.log"
    tail -n 15 "$evidence/$label.log"
    return "$status"
}
check dashboard-install npm ci --offline --ignore-scripts --no-audit --no-fund
check dashboard-tsc npx --no-install tsc --noEmit --incremental false
check dashboard-lint npm run lint
