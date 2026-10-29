#!/bin/bash
set -euo pipefail
scratch=/var/tmp/many-b1-b4-20261028
repo='/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/.closeout-worktrees/b1-b4'
evidence="$repo/docs/saas-delegation/b1-b4-evidence"
mkdir -p "$scratch" "$scratch/pg" "$scratch/socket"
chown postgres:postgres "$scratch/pg" "$scratch/socket"
python3 - "$evidence/source.zip" "$scratch" <<'PY'
import sys,zipfile
with zipfile.ZipFile(sys.argv[1]) as z:z.extractall(sys.argv[2])
PY
runuser -u postgres -- /usr/lib/postgresql/18/bin/pg_ctl -D "$scratch/pg" -l "$scratch/pg/server.log" -o "-k $scratch/socket -p 55438 -c listen_addresses=''" start
trap 'runuser -u postgres -- /usr/lib/postgresql/18/bin/pg_ctl -D "$scratch/pg" stop -m fast' EXIT
unshare --net bash "$evidence/focused-inner.sh"
