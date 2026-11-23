#!/bin/bash
set -euo pipefail
scratch=/var/tmp/many-t0-20261028
"$scratch/tools/bin/uv" pip freeze --python "$scratch/venv/bin/python" > "$scratch/evidence/dependencies.txt"
python3 "$(dirname "$0")/report.py"
runuser -u postgres -- /usr/lib/postgresql/18/bin/pg_ctl -D "$scratch/pg" stop -m fast
