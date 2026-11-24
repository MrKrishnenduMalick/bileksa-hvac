# Deployment

Do staging first with test accounts, then repeat for production. Onboarding a client after
deployment is in [client-onboarding.md](client-onboarding.md). The free public demo is a
separate deployment: [demo-deployment.md](demo-deployment.md). Hosting choice and costs:
[costs.md](costs.md).

## 1. Supabase

1. Create a project (region near your clients, e.g. `us-east`). Enable **Point-in-Time
   Recovery** or at least daily backups.
2. Auth → Providers: Email on. **Disable "Allow new users to sign up"**: client accounts are
   created only by BILEKSA invitations. Auth → URL configuration: Site URL = your site URL;
   add `<site-url>/reset-password` to the redirect URLs (invitations and password resets
   land there).
3. Auth → MFA: enable TOTP. Every BILEKSA admin must enrol (the admin API requires `aal2`).
4. Note: project URL, anon/publishable key, **service-role key** (backend only) and the
   database connection string (`postgresql+asyncpg://postgres.<ref>:<password>@<pooler-host>:5432/postgres`).
5. Run migrations: `DATABASE_URL=... uv run alembic upgrade head` (Railway runs this as the
   pre-deploy step). Migration `0004` is additive; it seeds the three packages and the cost
   settings, and moves existing clients' Vapi numbers to server-side routing on the next sweep.
6. Database → Extensions: enable `pg_cron` and `pg_net`, then run
   `supabase/pg_cron_sweep.sql` with your backend URL and `INTERNAL_SWEEP_SECRET`. The sweep
   (every 15 minutes) re-syncs assistants and phone routing, reconciles missed call reports,
   sends queued notification emails and checks that Vapi is reachable.

## 2. Vapi

1. Create an org (separate for staging and production). Copy the **private** API key.
2. Dashboard → Custom Credentials: create a **Bearer Token** credential with a long random
   token. That token is `VAPI_WEBHOOK_SECRET`; the credential's ID is `VAPI_CREDENTIAL_ID`.
3. With the backend deployed, open **Admin → Vapi tools → Sync tools to Vapi** (or run
   `uv run python -m app.cli setup-vapi-tools`). It creates or updates, by name, the six
   function tools (`get_business_information`, `check_service_area`, `save_customer_lead`,
   `create_callback_request`, `request_appointment`, `check_emergency_routing`) plus the
   native `transferCall` (dynamic destination) and `endCall`, stores their ids and re-syncs
   every assistant. Run it again after any tool change in `app/vapi/template.py`.
4. Choose the voice/model/transcriber by listening tests and set the template variables.
   Changing the prompt or tools: bump `TEMPLATE_VERSION`; the sweep PATCHes and re-verifies
   every assistant.
5. Concurrency: the pay-as-you-go plan allows 4 simultaneous calls for the whole org (Core,
   $29/month: 10). Upgrade before callers start getting busy signals (Admin → Usage & limits).
6. Phone numbers: each client's Vapi number is created **without** a fixed assistant, with
   server URL `<backend>/vapi/events` and a `fallbackDestination` (the client's direct line).
   Every inbound call therefore asks the backend first (`assistant-request`), which enforces
   minute limits and suspensions before any AI is used. Vapi includes 1 free number (5 on
   Core; inbound only); for paying clients import Twilio numbers ($1.15/month, can dial out
   for transfers): see [phone-integration.md](phone-integration.md).

## 3. Railway (backend)

1. New service from the GitHub repo, root directory `backend/` (uses `backend/Dockerfile` and
   `backend/railway.json`: migrations as the pre-deploy step, health check `/health/ready`, one
   replica — the in-process rate limiter assumes one instance).
2. Set every variable in [environment.md](environment.md). `SUPABASE_SERVICE_ROLE_KEY` and
   `VAPI_PRIVATE_KEY` are secrets: Railway only.
3. Generate a public domain; that URL is `PUBLIC_API_URL`.
4. Optional email: set the `SMTP_*` variables (any SMTP provider; Railway needs a paid plan for
   outbound SMTP). Without them, notifications still show in the dashboards.
5. Add an uptime monitor on `/health/ready` and Railway alerts for crashes/restarts.

## 4. Cloudflare Pages (frontend)

The frontend is a static export (`npm run build` → `frontend/out`); no Node server is needed.

1. Workers & Pages → Create → Pages → Connect to Git → the repo. Framework preset **None**,
   root directory `frontend`, build command `npm ci && npm run build`, output directory `out`.
2. Set the three `NEXT_PUBLIC_*` variables and `NODE_VERSION=22`. Do **not** set
   `NEXT_PUBLIC_DEMO_MODE` on the client site. Add your domain (Custom domains; SSL automatic).
3. The build writes `out/_headers` (CSP, HSTS, no microphone/camera, no framing).
4. Put the site URL into the backend's `FRONTEND_URL`/`CORS_ORIGINS` and the Supabase
   redirect URLs.

(Vercel also serves the static export, but its free Hobby plan is non-commercial.)

## 5. First BILEKSA admin

There is no public sign-up. Create the staff user in Supabase → Authentication → Users → **Add
user** (email + password), then:

```bash
cd backend
DATABASE_URL=... uv run python -m app.cli add-admin <user-uuid> <email>
```

Sign in at `/login`: you are sent to `/admin` and asked to set up two-step sign-in (TOTP).
Then set the BILEKSA alert email and check the cost assumptions in **Costs & profit**.

## 6. Go-live checklist

- [ ] `./scripts/check.sh` green on the release commit (and `RUN_E2E=1` locally); CI green.
- [ ] Admin → Vapi tools shows no missing tools.
- [ ] Staging: full journey with a real phone line, including the live call scenarios in
      [live-call-tests.md](live-call-tests.md) and the checks in
      [external-verification.md](external-verification.md).
- [ ] Legal review of privacy policy, terms, AI disclosure and call consent published.
- [ ] Emergency wording reviewed by an HVAC/safety professional.
- [ ] Backups/PITR confirmed and a restore rehearsed (`scripts/backup_restore_check.sh`).
- [ ] pg_cron job visible in `cron.job` and succeeding in `cron.job_run_details`.
- [ ] Admin accounts have MFA; `REQUIRE_ADMIN_MFA=true`; Supabase sign-ups disabled.
- [ ] `DEMO_MODE` is **not** set on the client API, `NEXT_PUBLIC_DEMO_MODE` not set on the site.
