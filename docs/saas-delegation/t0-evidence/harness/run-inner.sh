#!/bin/bash
set -euo pipefail
scratch=/var/tmp/many-t0-20261028
target=$1
label=$2
shift 2
ip link set lo up
redis-server --bind 127.0.0.1 --port 56379 --save '' --appendonly no >"$scratch/evidence/$label.redis.log" 2>&1 &
redis_pid=$!
trap 'kill "$redis_pid"; wait "$redis_pid" || true' EXIT
export PATH="$scratch/venv/bin:$PATH"
export APP_ENV=test
export TEST_DATABASE_URL="postgresql+psycopg://postgres@/many_test?host=$scratch/socket&port=55432"
# Only the fresh throwaway cluster; migration fixtures require this setting.
export DATABASE_URL="$TEST_DATABASE_URL"
export REDIS_URL=redis://127.0.0.1:56379/0
export META_APP_SECRET=t0-dummy-meta-secret META_WEBHOOK_VERIFY_TOKEN=t0-dummy-verify
export FACEBOOK_APP_SECRET='' META_WEBHOOK_SECRET='' JWT_SECRET=t0-dummy-jwt-secret-at-least-thirty-two-bytes
export APP_SECRET_KEY=t0-dummy-app-secret-at-least-thirty-two-bytes
export TOKEN_ENCRYPTION_KEY
TOKEN_ENCRYPTION_KEY=$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')
export OPENAI_API_KEY='' SENTRY_DSN='' RATE_LIMIT_ENABLED=true
export NO_PROXY='*' HTTP_PROXY='' HTTPS_PROXY='' ALL_PROXY=''
cd "$scratch/$target/backend"
test ! -e ../.env
test ! -e .env
printf 'DB host=%s db=many_test (fresh disposable cluster)\n' "$scratch/socket"
for i in {1..50}; do redis-cli -p 56379 ping >/dev/null 2>&1 && break; sleep .1; done
redis-cli -p 56379 flushall
printf 'APP_ENV=test TEST_DATABASE_URL=<explicit disposable many_test URL> pytest'
printf ' %q' "$@"
printf ' --junitxml=%s/evidence/%s.xml\n' "$scratch" "$label"
set +e
if [ "$1" = alembic ]; then
  shift
  APP_ENV=test TEST_DATABASE_URL="$TEST_DATABASE_URL" alembic "$@" >"$scratch/evidence/$label.log" 2>&1
else
  APP_ENV=test TEST_DATABASE_URL="$TEST_DATABASE_URL" pytest "$@" --junitxml="$scratch/evidence/$label.xml" >"$scratch/evidence/$label.log" 2>&1
fi
status=$?
set -e
tail -n 65 "$scratch/evidence/$label.log"
printf 'PYTEST_EXIT=%s\n' "$status"
exit "$status"
