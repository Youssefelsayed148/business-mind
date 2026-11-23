#!/bin/bash
set -euo pipefail
scratch=/var/tmp/many-closeout-t-fix-20261028-02
evidence='/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/docs/saas-delegation/t-closeout-evidence'
ip link set lo up
runuser -u postgres -- /usr/lib/postgresql/18/bin/pg_ctl -D "$scratch/pg" -l "$scratch/pg/server.log" -o "-k $scratch/socket -p 55462 -c listen_addresses=''" start
trap 'runuser -u postgres -- /usr/lib/postgresql/18/bin/pg_ctl -D "$scratch/pg" stop -m fast' EXIT
export PATH="/var/tmp/many-t0-20261028/venv/bin:$PATH" APP_ENV=test PGHOST="$scratch/socket" PGPORT=55462 PGUSER=postgres
export META_APP_SECRET=closeout-dummy-meta-secret JWT_SECRET=closeout-dummy-jwt-secret-at-least-thirty-two-bytes APP_SECRET_KEY=closeout-dummy-app-secret-at-least-thirty-two-bytes
export META_WEBHOOK_VERIFY_TOKEN=closeout-dummy-verify
export TOKEN_ENCRYPTION_KEY
TOKEN_ENCRYPTION_KEY=$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')
select_db() {
    createdb "$1"
    export TEST_DATABASE_URL="postgresql+psycopg://postgres@/$1?host=$PGHOST&port=$PGPORT" DATABASE_URL="postgresql+psycopg://postgres@/$1?host=$PGHOST&port=$PGPORT"
    printf 'DB host=%s db=%s\n' "$PGHOST" "$1" | tee -a "$evidence/fix-commands.log"
    test "$(psql -d "$1" -Atc 'SELECT current_database()')" = "$1"
}
check() {
    local label="$1"; shift
    printf 'APP_ENV=test TEST_DATABASE_URL=<explicit private target> ' >>"$evidence/fix-commands.log"
    printf '%q ' "$@" >>"$evidence/fix-commands.log"
    printf '\n' >>"$evidence/fix-commands.log"
    local start=$SECONDS
    set +e
    APP_ENV=test TEST_DATABASE_URL="$TEST_DATABASE_URL" "$@" >"$evidence/$label.log" 2>&1
    local status=$?
    set -e
    printf '%s exit=%s duration=%ss\n' "$label" "$status" "$((SECONDS-start))" | tee -a "$evidence/fix-commands.log"
    tail -n 12 "$evidence/$label.log"
}
cd /var/tmp/many-closeout-t-20261028-02/source/backend
select_db many_test_closeout_registry
check registry2 pytest tests/test_model_registry.py tests/test_processed_event_service.py tests/test_processed_event_migration.py -q --junitxml="$evidence/registry2.xml"
select_db many_test_closeout_drift
check fixed2-empty-head alembic upgrade head
check fixed2-drift alembic check
cd ..
select_db many_test_closeout_canary_fixed
check canary-fixed2 python -m unittest discover -s scripts -p 'test_*.py' -v
