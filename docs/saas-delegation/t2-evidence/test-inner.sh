#!/bin/bash
set -euo pipefail
scratch=/var/tmp/many-t0-20261028
repo='/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat'
evidence="$repo/docs/saas-delegation/t2-evidence"
target=/var/tmp/many-t2-20261028
ip link set lo up
redis-server --bind 127.0.0.1 --port 56379 --save '' --appendonly no >"$target/redis.log" 2>&1 &
redis_pid=$!
trap 'kill "$redis_pid"; wait "$redis_pid" || true' EXIT
export PATH="$scratch/venv/bin:$PATH"
export APP_ENV=test
export TEST_DATABASE_URL="postgresql+psycopg://postgres@/many_test?host=$scratch/socket&port=55432"
export DATABASE_URL=postgresql+psycopg://unused.invalid/many_test
export REDIS_URL=redis://127.0.0.1:56379/0
export META_APP_SECRET=t2-dummy-meta-secret META_WEBHOOK_VERIFY_TOKEN=t2-dummy-verify
export FACEBOOK_APP_SECRET='' META_WEBHOOK_SECRET='' JWT_SECRET=t2-dummy-jwt-secret-at-least-thirty-two-bytes
export APP_SECRET_KEY=t2-dummy-app-secret-at-least-thirty-two-bytes
export TOKEN_ENCRYPTION_KEY
TOKEN_ENCRYPTION_KEY=$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')
export OPENAI_API_KEY='' SENTRY_DSN='' RATE_LIMIT_ENABLED=true
export NO_PROXY='*' HTTP_PROXY='' HTTPS_PROXY='' ALL_PROXY=''
cd "$target"
test ! -e .env
test ! -e backend/.env
printf 'APP_ENV=test; explicit TEST_DATABASE_URL; DB host=%s db=many_test; DATABASE_URL unreachable sentinel\n' "$scratch/socket"
for i in {1..50}; do redis-cli -p 56379 ping >/dev/null 2>&1 && break; sleep .1; done
redis-cli -p 56379 flushall
python - <<'PY'
import os, sys
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
url = make_url(os.environ['TEST_DATABASE_URL'])
assert os.environ['APP_ENV'] == 'test' and url.database == 'many_test'
assert os.environ['DATABASE_URL'] == 'postgresql+psycopg://unused.invalid/many_test'
with create_engine(url).connect() as connection:
    assert connection.execute(text('SELECT current_database()')).scalar_one() == 'many_test'
sys.path.insert(0, 'backend')
from tests.conftest import DB_AVAILABLE, TEST_DATABASE_URL
assert DB_AVAILABLE and TEST_DATABASE_URL == os.environ['TEST_DATABASE_URL']
print('Conftest selects many_test only; Redis flushed; external network disabled.')
PY
python -m unittest discover -s scripts -p test_check_contract_copies.py -v >"$evidence/unittest.log" 2>&1
cat "$evidence/unittest.log"
python scripts/check_contract_copies.py | tee "$evidence/contract.log"
# Check the workflow's embedded Bash/Python syntax without executing its sudo/firewall commands.
python - <<'PY'
import ast, pathlib, subprocess
source = pathlib.Path('.github/workflows/saas-delegation.yml').read_text()
shell = source.split('        run: |\n', 1)[1].split('\n  contract-drift:', 1)[0]
shell = '\n'.join(line[10:] for line in shell.splitlines()) + '\n'
subprocess.run(['bash', '-n'], input=shell, text=True, check=True)
embedded = shell.split("python - <<'PY'\n", 1)[1].split('\nPY', 1)[0]
ast.parse(embedded)
print('Workflow embedded Bash and Python syntax OK; GitHub runtime UNVERIFIED.')
PY
set +e
APP_ENV=test TEST_DATABASE_URL="$TEST_DATABASE_URL" pytest backend/tests/test_saas_*.py --junitxml="$evidence/tests.xml" >"$evidence/tests.log" 2>&1
status=$?
set -e
tail -n 35 "$evidence/tests.log"
printf 'PYTEST_EXIT=%s\n' "$status"
exit "$status"
