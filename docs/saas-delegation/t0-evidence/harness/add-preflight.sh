#!/bin/bash
set -euo pipefail
repo='/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat'
git -c safe.directory="$repo" -C "$repo" archive HEAD scripts/preflight_prod.py | tar -x -C /var/tmp/many-t0-20261028/current
