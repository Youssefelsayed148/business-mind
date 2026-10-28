#!/bin/bash
set -euo pipefail
scratch=/var/tmp/many-t0-20261028
repo='/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat'
evidence="$repo/docs/saas-delegation/t2-evidence"
target=/var/tmp/many-t2-20261028
mkdir -p "$target"
python3 - "$evidence/snapshot.zip" "$target" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as archive:
    archive.extractall(sys.argv[2])
PY
if ! runuser -u postgres -- /usr/lib/postgresql/18/bin/pg_ctl -D "$scratch/pg" status >/dev/null; then
  runuser -u postgres -- /usr/lib/postgresql/18/bin/pg_ctl -D "$scratch/pg" -l "$scratch/pg/server.log" -o "-k $scratch/socket -p 55432 -c listen_addresses=''" start
fi
trap 'runuser -u postgres -- /usr/lib/postgresql/18/bin/pg_ctl -D "$scratch/pg" stop -m fast' EXIT
test "$(runuser -u postgres -- psql -h "$scratch/socket" -p 55432 -d many_test -Atc 'SELECT current_database()')" = many_test
unshare --net bash "$evidence/test-inner.sh"
