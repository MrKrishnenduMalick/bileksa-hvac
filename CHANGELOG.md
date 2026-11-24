# Changelog

## 2.2.0 — receptionist template v3 (unreleased)

US/Houston receptionist improvements. No database migration; existing clients, leads, tools
and assistants stay compatible.

- **Emergencies first:** the assistant records the emergency (`check_emergency_routing`) in the
  same turn as its first safety sentence. When no transfer is possible the tool itself requests
  the urgent callback, so the alert and callback exist even if the caller hangs up at once.
  End-of-call safety net: an emergency the AI never recorded is recorded from the call summary,
  and an emergency that ended before any transfer gets an urgent callback. One owner alert and
  one callback per call, however often the tool or the report repeats.
- New standard emergency categories: refrigerant leak; walk-in cooler or freezer failure.
  "Smoke" is now labelled "Smoke or fire". Stored client rules are unchanged.
- **Whole HVAC industry:** call-intent classification (repair, maintenance, installation,
  replacement, estimate, inspection, IAQ, ventilation, refrigeration, commercial/industrial,
  existing appointment); more service and equipment types (old values kept); broader word
  matching for service look-ups; site type kept in the after-call fallback.
- **Conversation:** short turns, one question at a time, no re-asking, numbers read in groups,
  ask to repeat instead of guessing, no announcing actions before they happen.
- **Tools:** clearer descriptions and field help; save the lead once, then only for new details;
  one callback per call.
- **Voice:** voice, model and transcriber unchanged. Optional speech settings (turn-taking,
  interruptions, silence timeout, Deepgram keyterms and smart format) are off by default and
  validated; see `docs/live-call-tests.md`.
- `TEMPLATE_VERSION` 3: run "Sync Vapi Tools", then the sweep re-syncs every assistant.

## 2.1.0 — 23 November 2026

Deployment round (audit: `docs/final-audit.md`).

- **Public demo** behind `DEMO_MODE` / `NEXT_PUBLIC_DEMO_MODE`, on its own Supabase project:
  Houston Comfort HVAC with realistic history, `/demo` sign-ins, scheduled reset, "Try the
  receptionist" (live browser voice via the Vapi Web SDK, or a labelled simulated call through
  the real gate, tools and end-of-call processing), admin Demo controls.
- **Voice spending guard:** budget from Vapi-reported cost, env-only ceiling and kill switch,
  per-call/day/IP limits, 6-hour pause on credit errors, automatic fallback to simulation.
- **Twilio numbers** can be imported per client instead of Vapi numbers.
- **Static frontend** for Cloudflare Pages (`output: "export"`, `_headers` generated per build);
  detail pages moved to `/admin/client?id=` and `/app/lead?id=`.
- Render free blueprint, demo pg_cron jobs, migrations-on-start option, demo env examples.
- Docs: demo deployment, hosting and costs, phone integration; Vapi plan facts updated.
- Migration `0005` (additive): `phone_lines.phone_provider`, demo voice settings.
- Tests: 126 backend (12 new for the demo), 17/17 browser workflows, 8/8 demo workflows.

## 2.0.0 — 23 November 2026

Final managed-service upgrade (spec "BILEKSA — Final AI Receptionist Upgrade"). Audit and gap
analysis: `docs/upgrade-gap-analysis.md`.

- **Managed service:** clients are created and configured only by BILEKSA (admin panel);
  owners are invited by email; public sign-up, public pricing and client-side configuration
  writes removed. Stripe gateway code removed (database columns kept, no destructive migration).
- **Strict minute limits:** every inbound call passes a server-side gate (Vapi
  `assistant-request`); over the limit or suspended → forwarded to the direct line, fallback
  number or unavailable message with no AI; calls in progress finish; 80 % / 100 % notifications.
- **Packages:** Starter $199 / 300 min, Professional $399 / 700 min, Premium $699 / 1,500 min,
  admin-editable; one package per client.
- **Password-confirmed admin actions:** assign/upgrade/downgrade package, change limit, renew,
  reset, suspend, restore, activate — verified with Supabase Auth on the server, rate-limited,
  audit-logged with before/after values.
- **Upgrade requests and manual payments**, setup fees hidden from clients.
- **Cost tracking:** configurable estimates ($0.15 Vapi + $0.01 telephony per minute, $41 fixed
  per client per month), other expenses, revenue and gross profit per client.
- **Vapi tools v2:** `check_service_area`, `request_appointment` (never claims a booking),
  FAQ/policy lookup, structured `success` results, admin alerts on tool failures, tool sync by
  name from the admin panel.
- **Reliability:** transfer → backup line → callback; optional warm transfer; automatic callback
  and owner alert when a transfer fails; phone-number `fallbackDestination`; Vapi outage
  detection; duplicate-lead prevention for repeat callers.
- **Emergencies:** per-client categories, approved extra instructions and routing on top of the
  fixed safety block; owner alerted immediately.
- **Notifications:** dashboard outbox for owners and BILEKSA, optional SMTP email with retries.
- **Dashboards:** simplified client dashboard (overview, calls with summaries, leads,
  callbacks & appointments, usage, packages, notifications, business info); admin console
  (clients with onboarding checklist, configuration tabs, phone & Vapi, payments; packages,
  upgrade requests, usage & limits, costs & profit, notifications, Vapi tools, errors, audit).
- Tests: 113 backend tests, 17 browser workflows.

## 1.0.0 — 16 November 2026

All five phases of the approved Architecture & Implementation Plan.

- **Phase 1 — Core system:** Supabase Auth (HS256 or JWKS), business registration, 14-table
  schema with RLS on every table, master assistant template with fixed safety block, fenced
  crash-safe provisioning (claim epoch, create intent, settle window, duplicate deletion),
  recovery sweep (startup + pg_cron + dashboard + admin).
- **Phase 2 — Working AI receptionist:** four Vapi Function tools, events webhook, dynamic
  transfer with honest results, end-of-call processing with lead fallback and "numbers to
  check", phone forwarding with real test-call verification, cross-business isolation tests.
- **Phase 3 — Dashboards:** customer dashboard (overview, calls, leads, callbacks, profile,
  services, areas, hours and holidays, transfer, receptionist and phone) and protected BILEKSA
  admin (businesses and mapping, retry, errors, usage and margin, audit log).
- **Phase 4 — Commercial:** Stripe Checkout, Customer Portal, signed webhooks, durable per-call
  overage events with reconciliation, payment grace and message-taking mode, setup checklist,
  marketing, pricing and contact pages.
- **Phase 5 — Security and launch readiness:** security review fixes, admin MFA gate, password
  reset, end-to-end browser checks, backup and restore rehearsal, Docker/Railway/Vercel config,
  CI, operations runbook and full documentation.

Note: the Stage 0 foundation (commit `8352e25` in an earlier workspace) could not be accessed
from this workspace and was recreated here with the same technology choices.
