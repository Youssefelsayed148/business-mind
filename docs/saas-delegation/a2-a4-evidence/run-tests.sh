#!/bin/bash
set -euo pipefail
scratch=/var/tmp/many-a2-a4-20261028
repo='/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/.closeout-worktrees/a2-a4'
evidence="$repo/docs/saas-delegation/a2-a4-evidence"
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
runuser -u postgres -- /usr/lib/postgresql/18/bin/pg_ctl -D "$scratch/pg" -l "$scratch/pg/server.log" -o "-k $scratch/socket -p 55443 -c listen_addresses=''" start
trap 'runuser -u postgres -- /usr/lib/postgresql/18/bin/pg_ctl -D "$scratch/pg" stop -m fast' EXIT
if ! runuser -u postgres -- psql -h "$scratch/socket" -p 55443 -d postgres -Atc "SELECT 1 FROM pg_database WHERE datname='many_test_a2_a4'" | /usr/bin/grep -qx 1; then
 runuser -u postgres -- createdb -h "$scratch/socket" -p 55443 many_test_a2_a4
fi
unshare --net bash "$evidence/test-inner.sh" "$@"
