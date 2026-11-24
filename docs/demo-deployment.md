# Public demo: deploy at ₹0

The demo is the real product (same code, same release) running against its **own** Supabase
project with `DEMO_MODE=true`. Nothing in it can reach a paying client's data: different
database, different Auth users, different Vapi assistant, and phone forwarding is switched off.

```
Visitor's browser ──▶ Cloudflare Pages (static site, free SSL, auto-deploy from GitHub)
      │  sign-in (Supabase Auth, demo project)        live voice (Vapi Web SDK + public key)
      ▼                                                  │
Render free web service (FastAPI, native Python, DEMO_MODE=true) ◀── Vapi tools / end-of-call report
      │
Supabase Free, demo project (Postgres + Auth + pg_cron)
      └─ pg_cron: /internal/sweep every 10 min (keeps API + DB awake), /internal/demo-reset every 6 h
```

## What the demo does

- **Houston Comfort HVAC** (fictional), on the Professional package, with two weeks of call
  history, leads, callbacks, appointment requests, an emergency, notifications and usage. A
  second fictional client (Bayou City Air) and an open upgrade request fill the admin side.
  All phone numbers are in the reserved fictional 555-01xx range.
- `/demo` publishes two sign-ins (owner and BILEKSA admin). They are reset with the data.
- **Owner → Try the receptionist**: a live browser call to the demo assistant (microphone),
  or a clearly labelled **simulated call** (5 scenarios) that runs the real minute-limit gate,
  the real tools and the real end-of-call processing, without voice and without voice cost.
  Both land in Call history, Leads and Callbacks like a phone call would.
- **Admin → Demo controls**: voice spending, live-voice switch, pause, and "Reset now".
- Blocked in the demo: phone-number assignment, owner invitations, Vapi provisioning for any
  business other than the demo company, and more than 12 clients.

## Voice spending guard

Vapi gives new accounts **$5 of free credits once** (not monthly; as of Nov 2026). Treat them as
roughly 30–45 minutes of live demo voice. The guard, in order:

1. **No card on the Vapi account.** This is the hard stop: Vapi cannot bill more than the
   credits. When they run out, the first failed call reports a credit error and live voice
   **pauses for 6 hours**; visitors get the simulation automatically.
2. **Budget**: live voice switches to simulation when Vapi's reported cost this month reaches
   the budget (default $4). The public admin screen can lower it, never raise it above
   `DEMO_VOICE_BUDGET_CAP_USD` (env, default $5).
3. Limits per call (`DEMO_VOICE_MAX_CALL_SECONDS`, 180, enforced by Vapi `maxDurationSeconds`
   and by the browser), per day (`DEMO_VOICE_MAX_CALLS_PER_DAY`, 25) and per visitor IP per hour
   (`DEMO_VOICE_CALLS_PER_IP_PER_HOUR`, 3).
4. `DEMO_LIVE_VOICE=false` (env) switches live voice off whatever the admin screen says. A
   visitor switching it off on the admin screen is undone by the next reset.
5. Restrict the Vapi **public** key (Vapi dashboard → API keys) to your demo origin and the demo
   assistant, so it can't be reused elsewhere. The private key stays on Render only.

Simulated and seeded calls never count toward the budget.

## Step by step

You need: a GitHub account, a Cloudflare account, a Supabase account, a Render account and a
Vapi account. All have free plans; none is charged by this setup.

### 1. GitHub

Push this repository to a **private** GitHub repo (e.g. `bileksa-hvac`). Render and
Cloudflare deploy from it automatically on every push to `main`.

### 2. Supabase (demo project)

1. Create a **new project** just for the demo (e.g. `bileksa-demo`, region US East). Never
   use the paying clients' project.
2. Authentication → Sign In / Providers → Email: on. **Turn off "Allow new users to sign up"**.
3. Authentication → URL Configuration: Site URL = your Pages URL (step 5); add
   `<pages-url>/reset-password` to Redirect URLs.
4. Project Settings → API: copy the project URL, the **anon/publishable** key (frontend) and
   the **service-role/secret** key (Render only).
5. Connect → Session pooler: copy the connection string and change the scheme to
   `postgresql+asyncpg://` → `DATABASE_URL`.
6. Database → Extensions: enable `pg_cron` and `pg_net` (used in step 6).

### 3. Vapi

1. Create an org for the demo. Do **not** add a payment method (that is the spending cap).
2. Copy the **private** key and the **public** key.
3. Custom Credentials → Bearer Token: create one with a long random token (`VAPI_WEBHOOK_SECRET`).
4. After Render is up (step 4): open the demo admin → **Vapi tools → Sync tools to Vapi**, or run
   `uv run python -m app.cli setup-vapi-tools` with the demo env. Put the tool ids it prints
   into `VAPI_TOOL_IDS` if you set them by env.
5. Restrict the public key to the Pages origin and (after step 6) the demo assistant id shown on
   Admin → Houston Comfort HVAC → Phone & Vapi.

### 4. Render (API)

1. New → **Blueprint** → pick the repo. Render reads `render.yaml` and creates
   `bileksa-demo-api` (free, native Python runtime, root `backend/`; no Docker).
2. Fill the variables marked "set in dashboard" (see `backend/.env.demo.example`). Generate the
   secrets with `openssl rand -base64 32` (`INTERNAL_SWEEP_SECRET`, both demo passwords).
3. Deploy. The start command runs the (additive) migrations, then the API, which seeds the
   demo and creates the two demo sign-ins. Check `https://<service>.onrender.com/health/ready`.

### 5. Cloudflare Pages (site)

1. Workers & Pages → Create → Pages → **Connect to Git** → pick the repo.
2. Build settings: framework preset **None**; root directory `frontend`; build command
   `npm ci && npm run build`; output directory `out`.
3. Environment variables (Production): the values in `frontend/.env.demo.example`
   (`NEXT_PUBLIC_DEMO_MODE=true`, API URL = Render URL, demo Supabase URL + anon key,
   `NODE_VERSION=22`).
4. Deploy. The build writes `_headers` (CSP that allows only this API, Supabase, and Vapi/Daily
   for voice; microphone allowed for this site only; HSTS).
5. Put the Pages URL into Render's `FRONTEND_URL` and `CORS_ORIGINS` and Supabase's Site URL.

**Custom domain (optional).** If your domain's DNS is on Cloudflare (free), Pages → Custom
domains → `demo.your-domain.com`; SSL is automatic. For the API, Render → Settings → Custom
domain → `api-demo.your-domain.com` and add the CNAME it shows in Cloudflare DNS (DNS only,
grey cloud). Then update the URLs in steps 4–5. Without a domain, `*.pages.dev` and
`*.onrender.com` work and cost nothing.

### 6. Scheduled jobs (Supabase pg_cron)

Run `supabase/demo_cron.sql` in the demo project's SQL editor with your Render URL and
`INTERNAL_SWEEP_SECRET`. Then trigger the first provisioning instead of waiting 10 minutes:

```bash
curl -X POST -H "Authorization: Bearer $INTERNAL_SWEEP_SECRET" https://<api>/internal/sweep
```

The demo assistant is created in Vapi and verified; **Try the receptionist** then shows
"Live voice".

### 7. Check it

- Open `<pages-url>/demo`, enter as the owner, open each page, run each simulated scenario,
  place one short live call and confirm it appears in Call history with a summary.
- Enter as the admin; check Demo controls shows the spend of that call.
- In Supabase SQL: `select jobname, schedule from cron.job;` and the run details query in
  `demo_cron.sql`.

## Free-tier limits, honestly

| Service | Free plan limit that matters | What we do about it |
| --- | --- | --- |
| Render free | Sleeps after 15 min without requests; ~1 min to wake; 750 instance-hours/month per workspace; may restart at any time | pg_cron calls the API every 10 min, so it normally stays awake; one service × 24 h × 31 d = 744 h fits. `/demo` retries for a minute while it wakes |
| Supabase Free | Pauses after 7 days of low activity; 500 MB DB; no downloadable backups | The 10-minute job is regular activity. If it ever pauses, "Restore" in the dashboard; data is kept. Demo data is disposable: the reset rebuilds it |
| Cloudflare Pages | 500 builds/month; unlimited static requests | One build per push |
| Vapi | $5 one-time credits; 4 concurrent calls; 1 free number | Spending guard above; the demo doesn't use a phone number |

No free service promises uptime. Expect the occasional cold start or maintenance window. Free
plans and their terms change; re-check them before relying on the demo for a sales meeting
(Render can be upgraded to Starter, $7/month, for a meeting-critical week).

**Recovery.** Code: redeploy from GitHub. Data: Admin → Demo controls → Reset now (or the
6-hourly job). Database lost or paused for good: create a new Supabase project, update the
three Supabase values on Render and Pages; the API migrates and reseeds itself on start.

## Why not Cloudflare Workers for the API?

Measured, not assumed: see [workers-free-test.md](workers-free-test.md). Most API requests need
roughly 15–40 ms of CPU in the Python runtime Workers uses, and Workers Free allows 10 ms; Python
Workers also support only synchronous SQLAlchemy and have no threads. Workers Paid ($5/month)
would fit, but the demo budget is ₹0. Pages serves the frontend; the API stays a normal container.
Alternative free container hosts if Render changes: Google Cloud Run (2M requests/month free,
needs a billing account, scales to zero with a few seconds' cold start) or Koyeb.
