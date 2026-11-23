#!/bin/bash
set -euo pipefail
scratch=/var/tmp/many-a5-a7-20261028
repo='/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/.closeout-worktrees/a5-a7'
evidence="$repo/docs/saas-delegation/a5-a7-evidence"
mkdir -p "$scratch" "$scratch/pg" "$scratch/socket"
chown postgres:postgres "$scratch/pg" "$scratch/socket"
test ! -e "$scratch/pg/PG_VERSION"
runuser -u postgres -- /usr/lib/postgresql/18/bin/initdb -D "$scratch/pg" -A trust >"$evidence/initdb.log"
python3 - "$evidence/source.zip" "$scratch" <<'PY'
import sys,zipfile
with zipfile.ZipFile(sys.argv[1]) as z:z.extractall(sys.argv[2])
PY
runuser -u postgres -- /usr/lib/postgresql/18/bin/pg_ctl -D "$scratch/pg" -l "$scratch/pg/server.log" -o "-k $scratch/socket -p 55437 -c listen_addresses=''" start
trap 'runuser -u postgres -- /usr/lib/postgresql/18/bin/pg_ctl -D "$scratch/pg" stop -m fast' EXIT
runuser -u postgres -- createdb -h "$scratch/socket" -p 55437 many_test_a5_a7
unshare --net bash "$evidence/test-inner.sh"
