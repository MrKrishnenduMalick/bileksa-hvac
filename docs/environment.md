# Environment variables

Secrets live only in Railway (backend) and in each provider's dashboard. The frontend receives
public values only. Staging and production use **separate** Supabase projects, Vapi orgs and
phone numbers. There is no payment gateway: payments are recorded by BILEKSA in the admin panel.

## Backend (Railway)

| Variable | Required | Notes |
| --- | --- | --- |
| `ENVIRONMENT` | yes | `production` disables API docs and enables HSTS |
| `DATABASE_URL` | yes | Supabase Postgres, `postgresql+asyncpg://…` (session pooler or direct) |
| `PUBLIC_API_URL` | yes | Public HTTPS URL of this backend; used in the tool, event and phone-number URLs given to Vapi |
| `FRONTEND_URL`, `CORS_ORIGINS` | yes | The Vercel URL(s). `FRONTEND_URL` is also the invite redirect target |
| `SUPABASE_URL` | yes | Project URL: JWKS sign-in verification, admin password re-verification, owner invites |
| `SUPABASE_JWT_SECRET` | no | Only for projects still on the legacy HS256 JWT secret |
| `SUPABASE_ANON_KEY` | yes | Publishable key; used server-side to re-verify an admin's password before package/limit/service changes. Without it those changes are refused (fail closed) |
| `SUPABASE_SERVICE_ROLE_KEY` | yes | **Secret.** Used only to invite client owners (Supabase Admin API). Never exposed to the frontend |
| `VAPI_PRIVATE_KEY` | yes | Server-side Vapi API key |
| `VAPI_WEBHOOK_SECRET` | yes | The token configured in the Vapi Custom Credential (Bearer) |
| `VAPI_CREDENTIAL_ID` | yes | ID of that Custom Credential; attached to tools, assistants and phone numbers |
| `VAPI_TOOL_IDS` | no | Only a fallback: `setup-vapi-tools` / Admin → Vapi tools stores the ids in the database |
| `VAPI_PHONE_AREA_CODE` | no | Default 713 |
| `VERIFY_CALLS_WITH_VAPI` | no | Default true: confirm each new call ID with Vapi's Call API |
| `VOICE_PROVIDER`, `VOICE_ID`, `MODEL_PROVIDER`, `MODEL_NAME`, `TRANSCRIBER_PROVIDER`, `TRANSCRIBER_MODEL` | no | Master template choices |
| `INTERNAL_SWEEP_SECRET` | yes | Bearer token pg_cron uses for `/internal/sweep` (long random) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_STARTTLS` | no | Email delivery for notifications (any SMTP provider). Railway allows outbound SMTP on paid plans only |
| `ADMIN_NOTIFICATION_EMAIL` | no | Default BILEKSA alert address (can be overridden in Admin → Costs & profit) |
| `LEAD_DEDUPE_HOURS` | no | Default 12: a repeat call from the same number reuses the open lead |
| `REQUIRE_ADMIN_MFA` | no | Default true: admin requests need a Supabase `aal2` session |
| `RATE_LIMIT_DASHBOARD`, `RATE_LIMIT_VAPI`, `RATE_LIMIT_REAUTH` | no | Requests per minute (300 / 600) and failed admin password attempts per minute (5) |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` | no | Only to import Twilio numbers into Vapi per client (backend-only secrets) |
| `RUN_MIGRATIONS_ON_START` | no | `true` on hosts without a release step (Render free, Cloud Run): the container runs `alembic upgrade head` before starting |
| `DEMO_MODE` | no | **Public demo only.** Never on the client deployment. Enables `/demo`, seeding, resets, simulated calls, and turns off admin MFA |
| `DEMO_OWNER_EMAIL`, `DEMO_OWNER_PASSWORD`, `DEMO_ADMIN_EMAIL`, `DEMO_ADMIN_PASSWORD` | demo | Published demo sign-ins (random values used nowhere else) |
| `VAPI_PUBLIC_KEY` | demo | Vapi public key for browser calls; restrict it to the demo origin and assistant |
| `DEMO_LIVE_VOICE`, `DEMO_VOICE_BUDGET_CAP_USD`, `DEMO_VOICE_MAX_CALL_SECONDS`, `DEMO_VOICE_MAX_CALLS_PER_DAY`, `DEMO_VOICE_CALLS_PER_IP_PER_HOUR`, `DEMO_MAX_CLIENTS` | demo | Voice spending guard: true / $5 / 180 s / 25 / 3 / 12 |

Cost assumptions ($0.15 Vapi, $0.01 telephony per minute, $41 fixed per client per month) and
the approaching-limit percentage are **not** environment variables: they are edited in the
admin panel (Costs & profit) and stored in `platform_settings`.

## Frontend (Cloudflare Pages, static export)

| Variable | Notes |
| --- | --- |
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase anon/publishable key (safe to expose; RLS protects data) |
| `NEXT_PUBLIC_API_URL` | Public URL of the backend |
| `NEXT_PUBLIC_DEMO_MODE` | `true` only on the public demo build: demo banner, `/demo`, Try the receptionist, demo controls, browser voice CSP |
| `NODE_VERSION` | `22` (Cloudflare Pages build image) |
