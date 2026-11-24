# Developer guide

## Requirements

- Node.js 22, npm 10+
- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- PostgreSQL 16 for tests and local development (Supabase in staging/production)
- Google Chrome (only for the end-to-end browser check)

## Run locally

```bash
# Database (any local Postgres 16)
createdb bileksa_dev
cd backend
cp .env.example .env            # fill in local values; never commit .env
uv sync
DATABASE_URL=postgresql+asyncpg://USER:PASS@localhost:5432/bileksa_dev uv run alembic upgrade head
uv run uvicorn app.main:app --reload        # http://localhost:8000/health

cd ../frontend
cp .env.example .env.local      # public values only
npm install
npm run dev                     # http://localhost:3000
```

Without real Supabase/Vapi accounts, use the end-to-end harness instead: it starts the
backend, the frontend and local stand-ins for those services (`scripts/e2e.sh`).

## Checks

```bash
./scripts/check.sh              # secrets, backend lint+tests, frontend lint+types+build, npm audit
RUN_E2E=1 ./scripts/check.sh    # …plus the browser check
./scripts/e2e.sh                # browser check only (screenshots in e2e/screenshots/)
./scripts/backup_restore_check.sh <source-db-url> <admin-db-url>
```

Backend tests create and migrate their own database (`bileksa_test`) through Alembic, so they
always test the real migrations. Override with `TEST_DATABASE_URL` / `TEST_ADMIN_DATABASE_URL`.

| Test file | Covers |
| --- | --- |
| `test_phase1_auth_registration.py` | Sign-in tokens, admin-only client creation, owner invites, admin configuration, no client writes |
| `test_phase1_provisioning.py` | Fenced provisioning: concurrency, slow Vapi, crashes, duplicates, retries |
| `test_phase1_rls.py` | RLS on every table, direct-query isolation, no customer writes |
| `test_phase2_receptionist.py` | Function tools, transfer, end-of-call processing, phone verification |
| `test_isolation.py` | Cross-business isolation for every Vapi entry point |
| `test_phase3_dashboards.py` | Metrics from real rows, leads/callbacks, admin protection |
| `test_managed_service.py` | Call gate and hard limits, password-confirmed service actions, packages, upgrade requests, payments, costs, notifications, transfer fallback, emergency rules, appointments, duplicate leads, failure scenarios |
| `test_phase5_security.py` | Route protection, rate limits, CORS, body limits, JWKS, emergencies |

## Migrations

```bash
cd backend
DATABASE_URL=... uv run alembic upgrade head
DATABASE_URL=... uv run alembic revision -m "describe change"
```

Any new table must enable RLS, revoke `anon`, revoke writes from `authenticated` and add a
member-read policy (copy `0002_row_level_security.py`). `test_phase1_rls.py` and
`test_phase5_security.py` fail if a table is missed.

## Operator commands

```bash
cd backend
uv run python -m app.cli setup-vapi-tools        # create/update the standard Vapi tools (same as Admin → Vapi tools)
uv run python -m app.cli sweep                   # run the recovery sweep now
uv run python -m app.cli add-admin <user-uuid> [email]
```

## Code map (backend)

| Path | Responsibility |
| --- | --- |
| `app/api/vapi_tools.py` | The Function Tool endpoints (structured success/failure) |
| `app/api/vapi_events.py` | assistant-request gate, transfer-destination-request (with fallback), status-update, end-of-call-report |
| `app/api/admin_clients.py` | Admin panel API: clients, configuration, phone, service actions, payments, packages, upgrades, costs, settings, Vapi tools |
| `app/api/client_account.py` | Client usage, packages, upgrade requests, notifications |
| `app/services/tenant.py` | Assistant/phone-number → business resolution and call binding |
| `app/services/usage.py` | Hard minute limits, the call gate, admin service actions |
| `app/services/phone_config.py` | Vapi phone-number routing (assistant-request + fallback), assignment, test call |
| `app/services/client_config.py` | Admin configuration writes (profile, routing, hours, services, areas, FAQs, emergency rules) |
| `app/services/notify.py` | Notification outbox and SMTP delivery |
| `app/services/costs.py` | Cost and profit report |
| `app/security/reauth.py` | Admin password re-verification (Supabase Auth) |
| `app/services/provisioning.py` | Fenced, crash-safe assistant provisioning |
| `app/vapi/template.py` | The master assistant template and fixed safety block |
| `app/services/calls.py` | End-of-call processing, phone verification, report reconciliation |
| `app/services/sweep.py` | The recovery sweep (startup, pg_cron, admin) |
| `app/security/` | Supabase JWT, Vapi credential, rate limits, RLS read sessions |
