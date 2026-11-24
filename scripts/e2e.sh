#!/usr/bin/env bash
# End-to-end browser check: real frontend + backend + Postgres, local stand-ins for
# Supabase Auth and Vapi. Requires Postgres on localhost and Google Chrome.
#   E2E_DB_ADMIN_URL   admin connection used to (re)create the e2e database
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ADMIN_URL="${E2E_DB_ADMIN_URL:-postgresql://bileksa:bileksa@localhost:5432/postgres}"
DB_NAME=bileksa_e2e; [ "${E2E_DEMO:-0}" = 1 ] && DB_NAME=bileksa_e2e_demo
DB_URL="postgresql+asyncpg://bileksa:bileksa@localhost:5432/${DB_NAME}"
LOGS="$ROOT/e2e/logs"; mkdir -p "$LOGS"

# E2E_DEMO=1 runs the public-demo build instead (DEMO_MODE API + NEXT_PUBLIC_DEMO_MODE site).
DEMO="${E2E_DEMO:-0}"
export SUPABASE_JWT_SECRET="e2e-jwt-secret-that-is-long-enough-123456"
export VAPI_WEBHOOK_SECRET="e2e-vapi-secret"
export INTERNAL_SWEEP_SECRET="e2e-sweep-secret"

psql "$ADMIN_URL" -qc "DROP DATABASE IF EXISTS ${DB_NAME} WITH (FORCE)" -qc "CREATE DATABASE ${DB_NAME}"
(cd "$ROOT/backend" && DATABASE_URL="$DB_URL" uv run alembic upgrade head)

stop_servers() {
  pkill -f "uvicorn tests.e2e_fake_services:app" 2>/dev/null || true
  pkill -f "uvicorn app.main:app --port 8000" 2>/dev/null || true
  pkill -f "out -l 3000" 2>/dev/null || true  # npx serve and its node child
  for port in 9100 8000 3000; do  # wait until each port is really free
    for _ in $(seq 1 30); do
      curl -s -o /dev/null --max-time 1 "http://localhost:$port" || break
      sleep 0.5
    done
  done
}
stop_servers  # never reuse a server (and its in-memory state) from an earlier run
trap stop_servers EXIT

DEMO_ENV=(); WEB_DEMO=()
if [ "$DEMO" = 1 ]; then
  DEMO_ENV=(DEMO_MODE=true DEMO_OWNER_PASSWORD=demo-owner-pass-1 DEMO_ADMIN_PASSWORD=demo-admin-pass-1
            VAPI_PUBLIC_KEY=e2e-public-key)
  WEB_DEMO=(NEXT_PUBLIC_DEMO_MODE=true)
fi

(cd "$ROOT/backend" && exec uv run uvicorn tests.e2e_fake_services:app --port 9100 >"$LOGS/fakes.log" 2>&1) &
(cd "$ROOT/backend" && env "${DEMO_ENV[@]}" DATABASE_URL="$DB_URL" ENVIRONMENT=development \
  VAPI_API_URL=http://localhost:9100/vapi-fake VAPI_PRIVATE_KEY=e2e-key VAPI_TOOL_IDS=t1,t2,t3,t4,t5,t6,t7,t8 \
  VERIFY_CALLS_WITH_VAPI=false SUPABASE_URL=http://localhost:9100 SUPABASE_ANON_KEY=e2e-anon \
  SUPABASE_SERVICE_ROLE_KEY=e2e-service-role \
  CORS_ORIGINS=http://localhost:3000 FRONTEND_URL=http://localhost:3000 RATE_LIMIT_DASHBOARD=2000 \
  PUBLIC_API_URL=http://localhost:8000 RUN_SWEEP_ON_STARTUP=false \
  uv run uvicorn app.main:app --port 8000 >"$LOGS/backend.log" 2>&1) &

(cd "$ROOT/frontend" && env "${WEB_DEMO[@]}" NEXT_PUBLIC_SUPABASE_URL=http://localhost:9100 NEXT_PUBLIC_SUPABASE_ANON_KEY=e2e-anon \
  NEXT_PUBLIC_API_URL=http://localhost:8000 npm run build >"$LOGS/frontend-build.log" 2>&1 \
  && npx -y serve@14 out -l 3000 >"$LOGS/frontend.log" 2>&1) &

for url in http://localhost:9100/sim/state http://localhost:8000/health http://localhost:3000; do
  for _ in $(seq 1 240); do curl -fs "$url" >/dev/null 2>&1 && break; sleep 1; done
done

export DATABASE_URL="$DB_URL"
if [ "$DEMO" = 1 ]; then
  # what the scheduled jobs do in production: (re)seed with sign-ins, then provision the assistant
  auth="Authorization: Bearer $INTERNAL_SWEEP_SECRET"
  curl -fsS -X POST -H "$auth" http://localhost:8000/internal/demo-reset >/dev/null
  curl -fsS -X POST -H "$auth" http://localhost:8000/internal/sweep >/dev/null
  sleep 2
  (cd "$ROOT/e2e" && node demo.mjs)
else
  (cd "$ROOT/e2e" && node run.mjs)
fi
