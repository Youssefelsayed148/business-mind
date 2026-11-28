# Sourced by the staging scripts. Never prints a value from the env file.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
ENV_FILE="${ENV_FILE:-.env.unified}"
COMPOSE=(docker compose -f docker-compose.unified.yml -f docker-compose.unified.prod.yml --env-file "$ENV_FILE")

die() { echo "ERROR: $*" >&2; exit 1; }

env_names_with_placeholder() { # prints NAMES (never values) whose value still contains CHANGE_ME
  grep -E '^[A-Za-z_][A-Za-z0-9_]*=.*CHANGE_ME' "$ENV_FILE" | cut -d= -f1 || true
}
