#!/bin/bash
set -euo pipefail
scratch=/var/tmp/many-closeout-t-20261028-02
evidence='/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/docs/saas-delegation/t-closeout-evidence'
ip link set lo up
ip -brief address >"$evidence/network.log"
runuser -u postgres -- /usr/lib/postgresql/18/bin/pg_ctl -D "$scratch/pg" -l "$scratch/pg/server.log" -o "-k $scratch/socket -p 55461 -c listen_addresses=''" start
redis-server --bind 127.0.0.1 --port 56379 --save '' --appendonly no >"$scratch/redis.log" 2>&1 &
redis_pid=$!
trap 'kill "$redis_pid"; wait "$redis_pid" || true; runuser -u postgres -- /usr/lib/postgresql/18/bin/pg_ctl -D "$scratch/pg" stop -m fast' EXIT
export PATH="/var/tmp/many-t0-20261028/venv/bin:/var/tmp/saas-closeout-tools/node-v24.22.1-linux-x64/bin:$PATH"
export APP_ENV=test PGHOST="$scratch/socket" PGPORT=55461 PGUSER=postgres
export REDIS_URL=redis://127.0.0.1:56379/0
export META_APP_SECRET=closeout-dummy-meta-secret META_WEBHOOK_VERIFY_TOKEN=closeout-dummy-verify
export FACEBOOK_APP_SECRET='' META_WEBHOOK_SECRET='' JWT_SECRET=closeout-dummy-jwt-secret-at-least-thirty-two-bytes
export APP_SECRET_KEY=closeout-dummy-app-secret-at-least-thirty-two-bytes
export TOKEN_ENCRYPTION_KEY
TOKEN_ENCRYPTION_KEY=$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')
export OPENAI_API_KEY='' SENTRY_DSN='' RATE_LIMIT_ENABLED=true NO_PROXY='*' HTTP_PROXY='' HTTPS_PROXY='' ALL_PROXY=''
select_db() {
    createdb "$1"
    export TEST_DATABASE_URL="postgresql+psycopg://postgres@/$1?host=$PGHOST&port=$PGPORT"
    export DATABASE_URL="$TEST_DATABASE_URL"
    printf 'DB host=%s db=%s\n' "$PGHOST" "$1" | tee -a "$evidence/commands.log"
    test "$(psql -d "$1" -Atc 'SELECT current_database()')" = "$1"
}
check() {
    local label="$1"; shift
    printf 'APP_ENV=test TEST_DATABASE_URL=<explicit private target> ' >>"$evidence/commands.log"
    printf '%q ' "$@" >>"$evidence/commands.log"
    printf '\n' >>"$evidence/commands.log"
    local start=$SECONDS
    set +e
    APP_ENV=test TEST_DATABASE_URL="$TEST_DATABASE_URL" "$@" >"$evidence/$label.log" 2>&1
    local status=$?
    set -e
    printf '%s exit=%s duration=%ss\n' "$label" "$status" "$((SECONDS-start))" | tee -a "$evidence/commands.log"
    tail -n 12 "$evidence/$label.log"
}
cd "$scratch/source/backend"
select_db many_test_closeout_t
python - <<'PY'
import os
from tests.conftest import DB_AVAILABLE, TEST_DATABASE_URL
assert DB_AVAILABLE and TEST_DATABASE_URL == os.environ['TEST_DATABASE_URL']
assert os.environ['DATABASE_URL'] == TEST_DATABASE_URL
print('Conftest target verified; isolated private cluster.')
PY
check many-backend pytest tests -q --junitxml="$evidence/many-backend.xml"
cd "$scratch/source"
select_db many_test_closeout_canary
check canary python -m unittest discover -s scripts -p 'test_*.py' -v
check contracts python scripts/check_contract_copies.py
cd backend
select_db many_test_closeout_empty
check heads alembic heads
check empty-head alembic upgrade head
check drift alembic check
check downgrade alembic downgrade 0022_whatsapp_opt_in
check reupgrade alembic upgrade head
select_db many_test_closeout_0022
check baseline-0022 alembic upgrade 0022_whatsapp_opt_in
check baseline-head alembic upgrade head
printf 'Completed Batch T initial checks.\n'
