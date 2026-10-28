#!/bin/bash
set -euo pipefail
scratch=/var/tmp/many-b2-20261028
repo='/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/.closeout-worktrees/b2'
evidence="$repo/docs/saas-delegation/b2-evidence"
mkdir -p "$scratch/source"
python3 - "$evidence/snapshot.zip" "$scratch/source" <<'PY'
import zipfile,sys
with zipfile.ZipFile(sys.argv[1]) as z: z.extractall(sys.argv[2])
PY
mkdir -p "$scratch/pg" "$scratch/socket"
chown postgres:postgres "$scratch/pg" "$scratch/socket"
if ! test -f "$scratch/pg/PG_VERSION"; then
 runuser -u postgres -- /usr/lib/postgresql/18/bin/initdb -D "$scratch/pg" -A trust >"$evidence/initdb.log" 2>&1
fi
runuser -u postgres -- /usr/lib/postgresql/18/bin/pg_ctl -D "$scratch/pg" -l "$scratch/pg/server.log" -o "-k $scratch/socket -p 55444 -c listen_addresses=''" start
trap 'runuser -u postgres -- /usr/lib/postgresql/18/bin/pg_ctl -D "$scratch/pg" stop -m fast' EXIT
if ! runuser -u postgres -- psql -h "$scratch/socket" -p 55444 -d postgres -Atc "SELECT 1 FROM pg_database WHERE datname='many_test_b2'" | /usr/bin/grep -qx 1; then
 runuser -u postgres -- createdb -h "$scratch/socket" -p 55444 many_test_b2
fi
unshare --net bash "$evidence/test-inner.sh" "$@"
