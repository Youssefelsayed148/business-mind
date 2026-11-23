#!/bin/bash
set -euo pipefail
scratch=/var/tmp/many-closeout-a5-20261028-01
evidence='/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/docs/saas-delegation/a5-closeout-evidence'
ip link set lo up
ip -brief address >"$evidence/network.log"
runuser -u postgres -- /usr/lib/postgresql/18/bin/pg_ctl -D "$scratch/pg" -l "$scratch/pg/server.log" -o "-k $scratch/socket -p 55463 -c listen_addresses=''" start
redis-server --bind 127.0.0.1 --port 56379 --save '' --appendonly no >"$scratch/redis.log" 2>&1 &
redis_pid=$!
trap 'kill "$redis_pid"; wait "$redis_pid" || true; runuser -u postgres -- /usr/lib/postgresql/18/bin/pg_ctl -D "$scratch/pg" stop -m fast' EXIT
export PATH="/var/tmp/many-t0-20261028/venv/bin:$PATH"
export APP_ENV=test PGHOST="$scratch/socket" PGPORT=55463 PGUSER=postgres
export REDIS_URL=redis://127.0.0.1:56379/0
export META_APP_SECRET=closeout-dummy-meta-secret META_WEBHOOK_VERIFY_TOKEN=closeout-dummy-verify
export FACEBOOK_APP_SECRET='' META_WEBHOOK_SECRET='' JWT_SECRET=closeout-dummy-jwt-secret-at-least-thirty-two-bytes
export APP_SECRET_KEY=closeout-dummy-app-secret-at-least-thirty-two-bytes
export TOKEN_ENCRYPTION_KEY
TOKEN_ENCRYPTION_KEY=$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')
export OPENAI_API_KEY='' SENTRY_DSN='' RATE_LIMIT_ENABLED=true NO_PROXY='*' HTTP_PROXY='' HTTPS_PROXY='' ALL_PROXY=''
createdb many_test_closeout_a5
export TEST_DATABASE_URL="postgresql+psycopg://postgres@/many_test_closeout_a5?host=$PGHOST&port=$PGPORT"
export DATABASE_URL="$TEST_DATABASE_URL"
printf 'DB host=%s db=many_test_closeout_a5\n' "$PGHOST" | tee "$evidence/commands.log"
test "$(psql -d many_test_closeout_a5 -Atc 'SELECT current_database()')" = many_test_closeout_a5
cd "$scratch/source/backend"
python - <<'PY'
import os
from tests.conftest import DB_AVAILABLE, TEST_DATABASE_URL
assert DB_AVAILABLE and TEST_DATABASE_URL == os.environ['TEST_DATABASE_URL']
assert os.environ['DATABASE_URL'] == TEST_DATABASE_URL
print('Conftest selects explicit private disposable target.')
PY
tests=(tests/test_meta*.py tests/test_*webhook*.py tests/test_facebook*.py tests/test_whatsapp_cloud_client.py tests/test_whatsapp_management_client.py tests/test_whatsapp_ids.py tests/test_whatsapp_message_dispatch.py tests/test_whatsapp_webhook*.py tests/test_instagram_token_refresh.py tests/test_send_private_reply.py tests/test_message_retry*.py tests/test_workspace_scoping.py)
mapfile -t tests < <(printf '%s\n' "${tests[@]}" | sort -u)
printf 'APP_ENV=test TEST_DATABASE_URL=<explicit private target> pytest ' >>"$evidence/commands.log"
printf '%q ' "${tests[@]}" >>"$evidence/commands.log"
printf '%q\n' '-q' "--junitxml=$evidence/tests.xml" >>"$evidence/commands.log"
start=$SECONDS
set +e
APP_ENV=test TEST_DATABASE_URL="$TEST_DATABASE_URL" pytest "${tests[@]}" -q --junitxml="$evidence/tests.xml" >"$evidence/tests.log" 2>&1
status=$?
set -e
printf 'pytest exit=%s duration=%ss\n' "$status" "$((SECONDS-start))" | tee -a "$evidence/commands.log"
tail -n 35 "$evidence/tests.log"
exit "$status"
