# Test record

Final verification after the deployment-readiness round (public demo, static export, Twilio
numbers), 23 November 2026, in the build workspace
(Ubuntu, Python 3.12, Node 22, PostgreSQL 16.15, Google Chrome for Testing 153). Every number
below is from an actual run; nothing is estimated.

## Summary

| Check | Command | Result |
| --- | --- | --- |
| Secret scan (tracked files and env files) | `scripts/check_secrets.sh` | PASS — none found |
| Backend lint and formatting | `ruff check .`, `ruff format --check .` | PASS |
| Backend unit and integration tests (real Postgres, real Alembic migrations) | `pytest` | **126 passed, 0 failed** |
| Models match migrations | `alembic check` | PASS — no differences |
| Migrations up → down → up, with pre-upgrade data | `alembic upgrade/downgrade` | PASS — existing rows kept; calls linked to their leads |
| Frontend lint, formatting, type check | `eslint`, `prettier --check`, `tsc --noEmit` | PASS |
| Frontend production build, static export (client build and demo build) | `npm run build`, `NEXT_PUBLIC_DEMO_MODE=true npm run build` | PASS (30 static routes each) |
| Container start command (migrations on start, then API) | Dockerfile `CMD` run with the venv | PASS — fresh database migrated to `0005`, `/health/ready` 200. The image itself was **not** built: no Docker daemon in the workspace |
| Migration `0005` down → up | `alembic downgrade -1 / upgrade head` | PASS |
| Dependency audit (frontend production deps) | `npm audit --omit=dev` | 0 vulnerabilities |
| End-to-end browser workflows (static site served as on Cloudflare Pages) | `scripts/e2e.sh` | **17 of 17 passed, 0 browser console errors** |
| Public-demo browser workflows | `E2E_DEMO=1 scripts/e2e.sh` | **8 of 8 passed, 0 browser console errors** |
| Backup and restore rehearsal | `scripts/backup_restore_check.sh` | PASS — identical row counts in all 22 tables (21 app tables + Alembic's), RLS and policies intact |
| Production-mode backend smoke test | manual | PASS — `/health` and `/health/ready` 200; `/docs`, `/openapi.json`, `/api/businesses` (removed self-registration) and `/stripe/webhook` (removed gateway) 404; HSTS present |

All of it is reproducible with `RUN_E2E=1 ./scripts/check.sh`.

## Backend tests by area (126)

| File | Tests | What is proven |
| --- | --- | --- |
| `test_demo.py` | 12 | Demo routes 404 when `DEMO_MODE` is off; seed builds a complete demo (Professional package, 100–700 used minutes, emergency, summaries, 555-01xx numbers only, second client, open upgrade request); reset keeps the same Vapi assistant and restores the published passwords and removes MFA factors; demo admin works without MFA; guardrails (no invites, no phone assignment, client cap, no Vapi provisioning for other businesses, transfers never dial); live voice: simulation without public key, reservation returns only public key + assistant + max length, 3 per IP per hour, budget from Vapi-reported cost of real calls only, budget ceiling enforced (422), credit errors pause for 6 h, admin can clear, env kill switch wins, reset undoes a visitor switching voice off; each of the 5 simulated scenarios runs the real gate, tools and end-of-call processing and is saved; simulation respects the minute limit; Twilio number import per client |

Earlier suites (unchanged apart from `test_phase5_security.py`, which now also proves every
demo route needs a session in demo mode):

| File | Tests | What is proven |
| --- | --- | --- |
| `test_managed_service.py` | 37 | **Hard limits:** AI answers within the limit; at the limit new calls are forwarded to the direct line (never the forwarded number) with no AI and zero billable minutes, while a call already in progress keeps working; status `limit_reached`; owner + BILEKSA notified exactly once; enforced even if the status was stale; 80 % warning once; onboarding with 0 minutes never uses the AI; suspended → fallback number → configured unavailable message; unknown number refused and logged; internal failure → 503 so Vapi uses `fallbackDestination`; assistant not ready → forwarded + admin alert; a phone number can't be used to reach another client. **Password-confirmed changes:** wrong password changes nothing and is audited; correct password applies and audits admin, client, action, previous and new values, timestamp; check session revoked; package assignment sets minutes; renewal resets usage; suspend/restore; activation requires a package; fails closed when Supabase is unreachable; 5 failed attempts per minute (successful ones never throttled); clients cannot reach any service action. **Upgrades and payments:** request → admin notified → nothing activated until the admin's password-confirmed activation, which completes the request; one open request at a time; tenant-isolated; payments and setup fees admin-only, also at the database (RLS). **Costs:** $41 + minutes × ($0.15 + $0.01) + other expenses, revenue from recorded payments, configurable; no cost data in any client response. **Calls:** transfer → backup line → callback; warm-transfer plan; failed transfer → automatic callback + owner alert; warm transfer "connected" only when Vapi completes it; per-client emergency rules (approved extra instructions, custom categories need instructions, emergency line first, transfer vs callback), owner alerted once per call; repeat caller reuses the open lead (closed leads aren't reused); appointments never confirmed; HVAC lead fields; FAQ/policy answers; call summary notification once despite webhook retries; owners never see BILEKSA notifications; email retries without blocking the call; notifications visible without email. **Vapi:** tool sync creates then updates by name and assistants pick up the ids; Vapi outage detected and reported; phone routing re-synced when numbers change and never assumed synced after a failure; missed reports reconciled by phone number. **Failures:** database down during a tool → honest failure; dropped call → lead + callback + appointment from Vapi's extraction (number not marked confirmed); incorrect and changed details; normal HVAC requests |
| `test_phase1_auth_registration.py` | 9 | Expired, wrong-audience, forged and service-role tokens refused; no self-registration and no client configuration writes; admin creates clients (validation, `onboarding`, 0 minutes); owner invite through Supabase (redirect to `/reset-password`, duplicate refused); admin configuration CRUD seen read-only by the client; every write audited; rename re-syncs the assistant without re-creating it |
| `test_phase1_provisioning.py` | 15 | 20 simultaneous requests → exactly one Vapi create; slow Vapi adopted; settle window; late creates deleted; crash recovery; superseded runner writes nothing; verification patched; 3 failures → `failed` → retry; template version change re-syncs; sweep protected; never "active" before phone verified |
| `test_phase1_rls.py` | 3 | RLS enabled on all 21 tables; direct queries as each user see only their own business; `authenticated` cannot write |
| `test_phase2_receptionist.py` | 19 | Vapi credential required; only approved facts; `check_service_area`; "not configured" instead of guessing; read-back confirmation; idempotent leads; callbacks never promise a time; emergency routing follows preference; fixed safety block; dynamic transfer returns only the mapped number and records "attempted" honestly; transfer refused after hours; end-of-call idempotency; approved prices not flagged; lead fallback; tool failure returns `success: false`, is logged and alerts BILEKSA; phone number created with gate routing (no fixed assistant, credential, fallback destination) → test call → verified → active; assistant must be ready; test window expiry; no routing number can loop to the forwarded line; missing reports reconciled |
| `test_isolation.py` | 6 | Each assistant sees only its own business; model-supplied IDs ignored; replayed call IDs refused; unknown/unverified assistants refused; Vapi Call API confirmation |
| `test_phase3_dashboards.py` | 7 | Overview metrics equal seeded rows; calls/leads/callbacks; cross-business access 404; every admin route (clients, payments, costs, settings, packages, upgrades, notifications…) refuses clients (403) and anonymous users (401); admin client detail, readiness checklist, cost report, re-provisioning and audit |
| `test_phase5_security.py` | 18 | Every route except health requires credentials (demo routes too, in demo mode); readiness; rate limits; CORS; security headers; submitted values never echoed; oversized/chunked bodies rejected; no write privileges for `authenticated`/`anon`; JWKS tokens; emergency scenarios for gas, CO, smoke, burning smell, sparks, dangerous malfunction and unknown; safety rules cover every required hazard |

## End-to-end browser workflows (17)

Real Chrome, real Next.js production build, real FastAPI backend and real Postgres; local
stand-ins for Supabase Auth and Vapi (`backend/tests/e2e_fake_services.py`; simulated calls go
through the `assistant-request` gate like a real Vapi number). Screenshots in `e2e/screenshots/`.

1. Public site: no pricing, no sign-up; `/pricing`, `/signup`, `/onboarding` return 404.
2. BILEKSA admin signs in; two-step enrolment; wrong code rejected.
3. Admin creates a client; exactly one Vapi assistant provisioned with the business name.
4. Admin configures routing, services, ZIP codes, hours, an FAQ and a custom emergency rule.
5. Package assignment: wrong password rejected, correct password applied.
6. Phone number assigned with gate routing (no fixed assistant, fallback destination), forwarding steps shown, test call verified.
7. Client activated (password).
8. Owner invited through Supabase, sets a password, signs in to their dashboard.
9. Calls produce leads (with equipment), callbacks, an appointment request (never booked), AI summaries, an emergency, owner notifications; unsourced amounts flagged, approved prices not.
10. Client sees business info read-only; no configuration controls.
11. Client requests an upgrade; admin sees it and activates it (password); client sees the new package.
12. Hard limit: limit lowered → `LIMIT_REACHED`; next call forwarded to the direct line with no AI; client sees the alert; raising the limit restores the AI.
13. Payment recorded; costs & profit page; audit log shows service changes and the rejected password; no cost data on any client page.
14. A second client sees none of the first client's data.
15. A client cannot open the admin area.
16. Password reset request and form.
17. Mobile layout and menu.

Deliberate errors (wrong MFA code, wrong admin password, removed pages) are excluded from the
console-error count; there were no others.

## Public-demo browser workflows (8)

Same setup with `DEMO_MODE=true` on the API and the demo build of the site; the scheduled jobs
(`/internal/demo-reset`, `/internal/sweep`) are called the way pg_cron calls them.

1. Home page shows the demo banner and "Try the live demo"; `/demo` lists both sign-ins.
2. Owner sign-in → populated dashboard, calls with an emergency, lead detail, usage on Professional.
3. Try the receptionist offers live browser voice while the budget lasts.
4. Simulated emergency call → transcript, outcome, "Simulated call:" summary → in Call history.
5. Admin sign-in without an authenticator app → both demo clients.
6. Demo controls: budget field capped at the operator ceiling; budget 0 → owner sees the
   simulation fallback and no live call button.
7. Owner invitation and phone-number assignment refused with a demo message.
8. Reset now → visitor's simulated call gone.

The live browser call itself (microphone, WebRTC, Vapi) cannot run headless here; the API side
of it (session reservation, limits, budget, credit-error pause) is covered by `test_demo.py`.

## Not verifiable in this environment

See [external-verification.md](external-verification.md) and the live script in
[live-call-tests.md](live-call-tests.md): real Supabase/Vapi accounts, live calls (speech,
accents, noise, interruptions, emergencies, transfer outcomes, `fallbackDestination` when the
backend is down), carrier forwarding, SMTP from Railway, Docker build, GitHub Actions, the live browser voice
call, deployment to Cloudflare Pages / Render / Supabase, and legal/safety review.
