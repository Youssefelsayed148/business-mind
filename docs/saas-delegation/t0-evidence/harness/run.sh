#!/bin/bash
set -euo pipefail
scratch=/var/tmp/many-t0-20261028
if ! runuser -u postgres -- /usr/lib/postgresql/18/bin/pg_ctl -D "$scratch/pg" status >/dev/null; then
  runuser -u postgres -- /usr/lib/postgresql/18/bin/pg_ctl -D "$scratch/pg" -l "$scratch/pg/server.log" -o "-k $scratch/socket -p 55432 -c listen_addresses=''" start
fi
if ! runuser -u postgres -- psql -h "$scratch/socket" -p 55432 -d postgres -Atc "SELECT 1 FROM pg_database WHERE datname='many_test'" | /usr/bin/grep -qx 1; then
  runuser -u postgres -- createdb -h "$scratch/socket" -p 55432 many_test
fi
unshare --net bash "$(dirname "$0")/run-inner.sh" "$@"
