#!/bin/bash
set -euo pipefail
target=/var/tmp/saas-closeout-tools
repo='/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/.closeout-worktrees/batch-c'
mkdir -p "$target"
uv=/var/tmp/many-t0-20261028/tools/bin/uv
"$uv" python install 3.12
"$uv" venv --python 3.12 "$target/venv"
"$uv" pip install --python "$target/venv/bin/python" -r "$repo/apps/api/requirements-dev.lock"
"$target/venv/bin/python" --version
test -f /usr/share/postgresql/18/extension/vector.control
printf 'Python 3.12 tooling and pgvector extension files ready; no DB connected.\n'
