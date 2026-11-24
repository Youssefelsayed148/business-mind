#!/usr/bin/env bash
# One-command wrapper for the unified Many + SaaS stack (LOCAL ONLY; never deploys).
#   scripts/dev-up.sh up              start the dev stack (needs .env.unified)
#   scripts/dev-up.sh test            throwaway no-egress stack, six e2e cases + nginx checks, then tear down (KEEP=1 leaves it running; NO_BUILD=1 reuses built images)
#   scripts/dev-up.sh down [--volumes]  stop both stacks (optionally drop their volumes)
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1   # Git Bash on Windows must not rewrite /e2e paths

BASE=(-f docker-compose.unified.yml)
E2E_ENV=(--env-file e2e/phase2/unified-e2e.env)
E2E=(-f docker-compose.unified.yml -f docker-compose.unified.e2e.yml "${E2E_ENV[@]}")

BUILD=(--build)
[ "${NO_BUILD:-}" = 1 ] && BUILD=()   # reuse already-built images (works offline)

need_docker() {
  docker info >/dev/null 2>&1 || { echo "Docker is not running. Start Docker Desktop and retry." >&2; exit 2; }
}

wait_healthy() {  # wait_healthy <service> <compose args...>
  local service="$1"; shift
  for _ in $(seq 1 90); do
    docker compose "$@" ps --format '{{.Service}} {{.Health}}' | grep -q "^${service} healthy" && return 0
    sleep 4
  done
  echo "Timed out waiting for ${service} to become healthy." >&2
  docker compose "$@" ps >&2 || true
  return 1
}

case "${1:-}" in
  up)
    need_docker
    [ -f .env.unified ] || { echo "Missing .env.unified: copy .env.unified.example and fill it in (never commit it)." >&2; exit 2; }
    docker compose "${BASE[@]}" --env-file .env.unified up -d "${BUILD[@]}"
    wait_healthy nginx "${BASE[@]}" --env-file .env.unified
    echo "Up. Many: http://localhost:${UNIFIED_HTTP_PORT:-8080}  SaaS web: http://saas.localhost:${UNIFIED_HTTP_PORT:-8080}  SaaS API: http://saas-api.localhost:${UNIFIED_HTTP_PORT:-8080}"
    ;;
  test)
    need_docker
    docker compose "${E2E[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
    docker compose "${E2E[@]}" up -d "${BUILD[@]}"
    wait_healthy nginx "${E2E[@]}"
    rc=0
    docker compose "${E2E[@]}" run --rm --no-deps driver || rc=1
    docker compose "${E2E[@]}" run --rm --no-deps nginx-checks || rc=1
    if [ "${KEEP:-}" = 1 ]; then echo "KEEP=1: stack left running (scripts/dev-up.sh down --volumes to remove)."; else
      docker compose "${E2E[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
    fi
    [ "$rc" -eq 0 ] && echo "TEST PASSED" || echo "TEST FAILED" >&2
    exit "$rc"
    ;;
  down)
    need_docker
    flag=()
    [ "${2:-}" = "--volumes" ] && flag=(-v)
    docker compose "${E2E[@]}" down "${flag[@]}" --remove-orphans || true
    if [ -f .env.unified ]; then docker compose "${BASE[@]}" --env-file .env.unified down "${flag[@]}" --remove-orphans || true; fi
    ;;
  *)
    echo "usage: $0 up | test | down [--volumes]" >&2
    exit 64
    ;;
esac
