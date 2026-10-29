#!/bin/bash
set -euo pipefail
scratch=/var/tmp/many-closeout-a5-20261028-01
evidence='/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/docs/saas-delegation/a5-closeout-evidence'
mkdir "$scratch/pg" "$scratch/socket"
chown postgres:postgres "$scratch/pg" "$scratch/socket"
runuser -u postgres -- /usr/lib/postgresql/18/bin/initdb -D "$scratch/pg" -A trust >"$evidence/initdb.log" 2>&1
exec unshare --net env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin HOME=/root LANG=C.UTF-8 bash "$evidence/inner.sh"
