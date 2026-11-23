#!/bin/bash
set -euo pipefail
export PATH="/var/tmp/saas-closeout-tools/node-v24.22.1-linux-x64/bin:$PATH"
cd '/mnt/d/Projects/Work Projects/The Osiris Labs/ManyOsirisChat/.closeout-worktrees/c4-c5'
node --version
npm ci --ignore-scripts
