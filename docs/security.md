# Security model

## Entry points

| Entry point | Caller | Authentication | Abuse controls |
| --- | --- | --- | --- |
| `/api/*` | Client owners (invited by BILEKSA) | Supabase JWT (HS256 secret or JWKS with issuer check), audience `authenticated`, then business membership | Read-only configuration; only lead status, callback/appointment status, upgrade requests and notification read flags can be written. Per-IP rate limit; reads run under RLS |
| `/admin/api/*` | BILEKSA staff | Supabase JWT + `admin_users` row + MFA (`aal2`) | Every write audit-logged. Package, limit, period, suspend/restore and activation additionally need the admin's **password**, verified server-side with Supabase Auth (fails closed; 5 failed attempts per minute) |
| `/vapi/tools/*`, `/vapi/events` | Vapi | Vapi Custom Credential (Bearer or `X-Vapi-Secret`), constant-time compare; then assistant/phone-number → business mapping and call binding | Per-assistant rate limit; 256 KB body cap (also for chunked bodies); argument sanitising |
| `/internal/sweep` | Supabase pg_cron | Bearer `INTERNAL_SWEEP_SECRET` | Idempotent |
| `/health`, `/health/ready` | Monitors | none | Return no data |

`test_every_route_requires_credentials` enumerates every route and fails if any (other than
health) answers without credentials.

## Isolation

- Business resolved only from Vapi's call object via the server-side mapping; tool arguments
  naming a business, assistant or call are discarded.
- Calls are bound to one business; replaying a call ID under another assistant is refused and
  logged (`vapi_call_binding_mismatch`).
- Only `verified`/`active` assistants are mapped; duplicates or deleted assistants are refused.
- All backend queries filter by `business_id`; dashboard reads also run as role
  `authenticated` with the user's claims so RLS applies.
- RLS enabled on all 21 tables; `anon` has no privileges; `authenticated` has SELECT only on
  its own business's rows; `payment_records`, `expenses` and `platform_settings` are invisible
  to customers; owners only see owner-audience notifications.
- No self-registration: tenants are created by admins; owners are linked by Supabase invite.
- Clients never receive provider credentials, internal costs, setup fees or service controls;
  tests assert customer responses contain no cost data.

## Other controls

- Secrets only in Railway/provider dashboards (incl. the Supabase service-role key used for
  invites); frontend gets public keys only;
  `scripts/check_secrets.sh` runs in CI.
- CORS limited to the frontend origin; no cookies (Bearer tokens), so no CSRF surface.
- Security headers on API and site (CSP, HSTS in production, frame denial, nosniff,
  referrer policy, permissions policy). API docs disabled in production.
- Errors never echo submitted values or stack traces.
- Caller speech, model arguments and dashboard text are treated as untrusted: validated,
  length-limited, control characters stripped, never placed in the system prompt.
- The emergency safety block is fixed in the master template; customers and documents cannot
  change it; it does not depend on any tool or transfer succeeding.
- Recordings disabled; transcripts are processed transiently and never stored.
- Audit log is append-only and does not store full phone numbers or secrets.
- Container runs as a non-root user.

## Phase 5 review findings (fixed)

| Finding | Fix |
| --- | --- |
| Rate limiting covered only writes | Router-level limits on all dashboard, admin, billing and phone routes |
| Rate-limit key used the client-controlled first `X-Forwarded-For` entry | Uses the proxy-added last entry |
| Body size check relied on `Content-Length` | Streaming cap for Vapi and Stripe bodies |
| Admin access did not require MFA | `aal2` required (configurable for staging) |
| No readiness probe | `/health/ready` checks the database |
| Approved prices were flagged as unsourced numbers | Compared against the business's approved prices too |

## Final-upgrade review findings (fixed)

| Finding | Fix |
| --- | --- |
| Anyone could self-register and create a tenant + Vapi assistant | Removed; admin-only client creation with owner invitations |
| Usage beyond the plan was billed automatically | Hard limits enforced per call at the `assistant-request` gate |
| Phone numbers pointed straight at the assistant (nothing could stop a call) | Numbers use `assistant-request` routing with a `fallbackDestination` |
| Fallback numbers were not checked against the forwarded line (call loops) | All routing numbers validated, and filtered again at call time |
| Clients could change their own transfer numbers and prices | Configuration writes are admin-only |

## Deployment-round findings (fixed)

| Finding | Fix |
| --- | --- |
| `Permissions-Policy` denied the microphone everywhere; CSP had no Vapi/Daily hosts; leftover Stripe `form-action` | Headers generated per build: microphone and Vapi/Daily only on the demo build; Stripe removed |
| Security headers lived in `next.config` `headers()`, which a static export ignores | `scripts/write-headers.mjs` writes `_headers` for Cloudflare Pages on every build |
| The demo admin sign-in is public, so it could raise the voice budget or turn voice back on after a credit pause | Budget can't exceed the env-only `DEMO_VOICE_BUDGET_CAP_USD`; env `DEMO_LIVE_VOICE` kill switch; no card on the Vapi org is the hard cap |
| A visitor could add an MFA factor or change a demo password and lock others out | Reset restores the published passwords and deletes MFA factors through the Auth admin API; demo admin works without MFA (demo database only) |
| Demo sign-ins were never created if Supabase was unreachable at first start | Start-up repairs missing demo sign-ins; resets recreate them |

Demo isolation is physical: separate Supabase project and Auth users, separate Vapi org.
`DEMO_MODE` must never be set on the client deployment (go-live checklist).

## Known limits

- The in-process rate limiter assumes one backend instance (`numReplicas: 1`). Scaling out
  needs a shared counter (Postgres) — not needed at launch.
- `script-src 'unsafe-inline'` is required by Next.js hydration scripts.
- Penetration testing by a third party has not been done (recommended before scale).
