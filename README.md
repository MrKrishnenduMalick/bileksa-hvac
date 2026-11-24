# BILEKSA HVAC

**Your HVAC Business. Your AI Receptionist.** A managed AI receptionist service for HVAC
contractors. BILEKSA creates and configures each client in the admin panel, assigns a package
with a hard minute limit, connects the client's phone line and invites the owner to a simple
dashboard of calls, leads, callbacks, appointments and usage.

```
Caller → Vapi number → (assistant-request: limit check) → Vapi assistant → Vapi tool call
       → FastAPI endpoint → business logic / Supabase → structured result → Vapi → caller
```

- **Vapi** runs every conversation and owns every tool (6 BILEKSA function tools + native
  `transferCall` and `endCall`), attached directly to each client's assistant.
- **FastAPI** authenticates, decides per call whether the AI may answer (hard minute limits,
  suspension), resolves the client from server-side mappings, runs one business operation and
  returns `success: true/false`. No AI orchestration.
- **Supabase** holds the data (21 tables, Row Level Security on every table) and sign-in.
- **No payment gateway**: packages are sold privately; BILEKSA records payments and activates
  packages with password confirmation.

## Repository layout

```
frontend/   Next.js 16 app: marketing site (no public pricing/sign-up), client dashboard, BILEKSA admin
backend/    FastAPI API, Vapi tool/event endpoints, admin API, Alembic migrations, tests
e2e/        Browser check of the main workflows (real Chrome, see scripts/e2e.sh)
supabase/   pg_cron SQL: recovery sweep (clients), sweep + reset (public demo)
render.yaml Render blueprint for the free public-demo API
scripts/    check.sh (all checks), e2e.sh, backup_restore_check.sh, check_secrets.sh
docs/       Developer, architecture, deployment, operations, security and test records
```

## Start here

| You want to… | Read |
| --- | --- |
| Run it locally or work on the code | [docs/README.md](docs/README.md) |
| Understand how it works | [docs/architecture.md](docs/architecture.md) |
| Deploy to production | [docs/deployment.md](docs/deployment.md) and [docs/environment.md](docs/environment.md) |
| Deploy the free public demo | [docs/demo-deployment.md](docs/demo-deployment.md) |
| Hosting choice and monthly costs | [docs/costs.md](docs/costs.md) |
| Connect a client's phone line | [docs/phone-integration.md](docs/phone-integration.md) |
| See the final audit (deployment round) | [docs/final-audit.md](docs/final-audit.md) |
| Onboard a new HVAC client | [docs/client-onboarding.md](docs/client-onboarding.md) |
| Test with real calls | [docs/live-call-tests.md](docs/live-call-tests.md) |
| See the final-upgrade audit and gap analysis | [docs/upgrade-gap-analysis.md](docs/upgrade-gap-analysis.md) |
| Operate it day to day | [docs/operations.md](docs/operations.md) |
| See the security model | [docs/security.md](docs/security.md) |
| See what was tested and the results | [docs/testing.md](docs/testing.md) |
| See what still needs live accounts, real calls or legal review | [docs/external-verification.md](docs/external-verification.md) |
| Decisions and their reasons | [docs/decisions.md](docs/decisions.md) |

## Status

The final managed-service upgrade is implemented and tested locally with real Postgres and
stand-ins for Supabase Auth and Vapi (results in [docs/testing.md](docs/testing.md)). Going
live still requires real accounts, live phone testing and legal/safety review; the exact list
is in [docs/external-verification.md](docs/external-verification.md).
