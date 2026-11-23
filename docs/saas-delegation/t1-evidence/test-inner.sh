#!/bin/bash
set -euo pipefail
scratch=/var/tmp/many-t0-20261028
repo='/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat'
evidence="$repo/docs/saas-delegation/t1-evidence"
ip link set lo up
redis-server --bind 127.0.0.1 --port 56379 --save '' --appendonly no >/var/tmp/many-t1-20261028/redis.log 2>&1 &
redis_pid=$!
trap 'kill "$redis_pid"; wait "$redis_pid" || true' EXIT
export PATH="$scratch/venv/bin:$PATH"
export APP_ENV=test
export TEST_DATABASE_URL="postgresql+psycopg://postgres@/many_test?host=$scratch/socket&port=55432"
# Settings requires DATABASE_URL even though conftest uses TEST_DATABASE_URL.
# Supply an unreachable sentinel; it is never the test database target.
export DATABASE_URL=postgresql+psycopg://unused.invalid/many_test
export REDIS_URL=redis://127.0.0.1:56379/0
export META_APP_SECRET=t1-dummy-meta-secret META_WEBHOOK_VERIFY_TOKEN=t1-dummy-verify
export FACEBOOK_APP_SECRET='' META_WEBHOOK_SECRET='' JWT_SECRET=t1-dummy-jwt-secret-at-least-thirty-two-bytes
export APP_SECRET_KEY=t1-dummy-app-secret-at-least-thirty-two-bytes
export TOKEN_ENCRYPTION_KEY
TOKEN_ENCRYPTION_KEY=$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')
export OPENAI_API_KEY='' SENTRY_DSN='' RATE_LIMIT_ENABLED=true
export NO_PROXY='*' HTTP_PROXY='' HTTPS_PROXY='' ALL_PROXY=''
cd /var/tmp/many-t1-20261028/backend
test ! -e ../.env
test ! -e .env
printf 'APP_ENV=test; TEST_DATABASE_URL explicit; DB host=%s db=many_test; DATABASE_URL unreachable sentinel\n' "$scratch/socket"
for i in {1..50}; do redis-cli -p 56379 ping >/dev/null 2>&1 && break; sleep .1; done
redis-cli -p 56379 flushall
python - <<'PY'
import os
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
url = make_url(os.environ['TEST_DATABASE_URL'])
assert os.environ['APP_ENV'] == 'test' and url.database == 'many_test'
assert os.environ['DATABASE_URL'] == 'postgresql+psycopg://unused.invalid/many_test'
with create_engine(url).connect() as connection:
    assert connection.execute(text('SELECT current_database()')).scalar_one() == 'many_test'
print('Disposable database preflight passed; Redis flushed; external network disabled.')
from tests.conftest import DB_AVAILABLE, TEST_DATABASE_URL
assert DB_AVAILABLE and TEST_DATABASE_URL == os.environ['TEST_DATABASE_URL']
print('Conftest selects only the explicit disposable TEST_DATABASE_URL.')
PY
set +e
APP_ENV=test TEST_DATABASE_URL="$TEST_DATABASE_URL" pytest tests/test_saas_contract_vectors.py tests/test_saas_signing.py -v --junitxml="$evidence/tests.xml" >"$evidence/tests.log" 2>&1
status=$?
set -e
cat "$evidence/tests.log"
printf 'PYTEST_EXIT=%s\n' "$status"
exit "$status"
