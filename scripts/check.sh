#!/usr/bin/env bash
# Runs every automated check (same as CI). Needs Postgres on localhost for backend tests.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "== secrets";   "$ROOT/scripts/check_secrets.sh"
echo "== backend";   (cd "$ROOT/backend" && uv run ruff check . && uv run ruff format --check . && uv run pytest -q)
echo "== frontend";  (cd "$ROOT/frontend" && npx eslint && npx prettier --check "src/**/*.{ts,tsx}" && npx tsc --noEmit && npm run build \
  && NEXT_PUBLIC_DEMO_MODE=true npm run build)  # client build, then the public-demo build
echo "== audit";     (cd "$ROOT/frontend" && npm audit --omit=dev)
if [ "${RUN_E2E:-0}" = "1" ]; then
  echo "== e2e";      "$ROOT/scripts/e2e.sh"
  echo "== e2e demo"; E2E_DEMO=1 "$ROOT/scripts/e2e.sh"
fi
echo "ALL CHECKS PASSED"
