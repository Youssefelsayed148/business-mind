#!/bin/bash
set -euo pipefail
repo='/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat'
scratch=/var/tmp/many-t0-20261028
mkdir -p "$scratch"
python3 -m venv "$scratch/tools"
"$scratch/tools/bin/pip" install uv
"$scratch/tools/bin/uv" python install 3.11
"$scratch/tools/bin/uv" venv --python 3.11 "$scratch/venv"
git -c safe.directory="$repo" -C "$repo" worktree add --detach "$scratch/baseline" 5cc60c7
mkdir -p "$scratch/current"
git -c safe.directory="$repo" -C "$repo" archive HEAD backend | tar -x -C "$scratch/current"
"$scratch/tools/bin/uv" pip install --python "$scratch/venv/bin/python" -r "$scratch/current/backend/requirements.txt"
unshare --net true
mkdir -p "$scratch/pg" "$scratch/socket" "$scratch/evidence"
chown postgres:postgres "$scratch/pg" "$scratch/socket"
runuser -u postgres -- /usr/lib/postgresql/18/bin/initdb -D "$scratch/pg" -A trust
runuser -u postgres -- /usr/lib/postgresql/18/bin/pg_ctl -D "$scratch/pg" -l "$scratch/postgres.log" -o "-k $scratch/socket -p 55432 -c listen_addresses=''" start
runuser -u postgres -- createdb -h "$scratch/socket" -p 55432 many_test
redis-server --port 0 --unixsocket "$scratch/redis.sock" --save '' --appendonly no --daemonize yes --pidfile "$scratch/redis.pid" --logfile "$scratch/redis.log"
