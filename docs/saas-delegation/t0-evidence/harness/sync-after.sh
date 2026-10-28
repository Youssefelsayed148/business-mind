#!/bin/bash
set -euo pipefail
scratch=/var/tmp/many-t0-20261028
repo='/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat'
if [ ! -d "$scratch/after" ]; then
  cp -a "$scratch/current" "$scratch/after"
fi
for file in conftest.py test_campaigns.py test_whatsapp_outreach_settings_migration.py test_rate_limit_isolation.py; do
  cp "$repo/backend/tests/$file" "$scratch/after/backend/tests/$file"
done
