# Architecture

One Next.js frontend (static export on Cloudflare Pages), one FastAPI backend (Railway), one
Supabase Postgres database, Vapi for voice. The public demo is the same code deployed a second
time with `DEMO_MODE` on its own Supabase project (see "Public demo" below). No payment gateway, queues, workers, Redis, microservices or AI orchestration
framework.

```
Customer call → Vapi number ──assistant-request──▶ FastAPI gate (limit / suspension check)
                     │  ◀── assistantId  (AI answers)   or   destination (forward, no AI)
                     ▼
              Vapi AI assistant → Vapi tool call → FastAPI endpoint → business logic / DB
                     ▲                                                    │
                     └──────────── structured result (success true/false) ┘
```

## Who owns what

| Concern | Vapi | FastAPI + Supabase |
| --- | --- | --- |
| Speech, conversation, deciding what to say | Yes | No |
| Tool definitions and when to call them | Yes (standard tools attached to every assistant) | No orchestration; endpoints only |
| Business facts, FAQs, policies | No; must call a tool | Yes (configured by BILEKSA) |
| Which business a call belongs to | Supplies `call.assistantId` / `call.phoneNumberId` | Decides from its own mappings |
| Whether the AI may answer at all | Asks via `assistant-request` | Hard minute limit, suspension, readiness |
| Safety instructions | Fixed block in the master prompt | Per-client additions and routing |
| Transfer and hang-up | Native `transferCall` / `endCall` | Chooses the number; records the result honestly |
| After-call processing | Sends the end-of-call report | Summary, outcome, usage, lead fallback, notifications |

## One call

1. The caller dials the client's own number; the carrier forwards it to the client's Vapi
   number. That number has **no fixed assistant**, so Vapi asks `/vapi/events`
   (`assistant-request`).
2. The gate (`app/services/usage.py::gate`) resolves the client from the phone-number mapping
   and checks: suspended? minute limit reached? assistant ready? If the AI may answer it returns
   the client's `assistantId`; otherwise it forwards the call (`destination`) to the client's
   direct line, then the fallback number, or speaks the configured unavailable message. If the
   backend fails, Vapi uses the number's `fallbackDestination`.
3. The assistant greets with the business name and calls tools for every fact or action. Vapi
   POSTs to `/vapi/tools/<name>`; FastAPI verifies the credential, resolves the business from
   the call object, binds the call to that business, runs one operation and returns
   `{"results":[{"toolCallId","result"}]}` where `result` always has `success`.
4. Transfer: `transferCall` has no destinations, so Vapi asks `/vapi/events`
   (`transfer-destination-request`). First attempt: emergency line (emergencies) or transfer
   number; second attempt on the same call: fallback number; then refused so the AI takes a
   callback. Optional warm-transfer mode returns the caller to the AI when nobody answers.
5. After the call, the end-of-call report stores duration, summary, transfer outcome and lead
   fallback from Vapi's structured data; creates a callback if a transfer failed; updates
   usage (`after_call`: 80 % and 100 % notifications, `limit_reached`); notifies the owner.

## The tools (template v2)

| Tool | Purpose |
| --- | --- |
| `get_business_information` | Services, approved prices, hours/open-now, FAQs, policies, general info. "not configured" instead of guessing |
| `check_service_area` | ZIP coverage |
| `save_customer_lead` | Creates/updates the caller's lead (name, confirmed number, address, ZIP, equipment, problem, urgency, new/existing, notes). A repeat call from the same number within 12 h reuses the open lead |
| `create_callback_request` | Callback request; never promises a time |
| `request_appointment` | Appointment **request**; returns `booked: false` (no booking integration is connected) |
| `check_emergency_routing` | Records the emergency, returns approved extra instructions and whether to transfer; notifies the owner immediately |
| `transferCall`, `endCall` | Vapi native |

Every tool validates input, is idempotent for the same call, returns `success`, and on any
error returns `success: false` with what to tell the caller (logged + BILEKSA alerted).

## Packages, limits and service status

`packages` (Starter/Professional/Premium; admin-editable price, minutes, features). Each client
has one package, its own `included_minutes` limit and a usage period. Usage = billable seconds
of AI calls that ended since the period start. Status: `onboarding → active ↔ limit_reached`,
`suspended`. Only admins change packages, limits, periods and status, each confirmed with the
admin's password (verified by Supabase Auth on the server) and audit-logged with before/after
values. Clients can only request upgrades. Payments are recorded manually; there is no gateway.

## Notifications

`notifications` is an outbox: each event is stored once (`dedupe_key`), shown in the owner or
admin dashboard, and emailed by SMTP when configured (retried by the sweep, max 5 attempts).
Owner: call summaries, emergencies, limit warnings, service changes. BILEKSA: upgrade requests,
limits, tool failures, failed calls, assistant/Vapi outages.

## Tenant isolation

- Business resolved only from Vapi's call object via server-side mappings
  (`assistants.vapi_assistant_id`, `phone_lines.vapi_phone_number_id`); when both are present
  they must agree. Tool arguments naming a business, assistant or call are ignored.
- Each call is bound to one business on first sight; a mismatch is refused and logged.
- Every backend query filters by `business_id`; dashboard reads also run as Postgres role
  `authenticated` with the user's claims so RLS applies. RLS is on every table; admin-only
  tables (`payment_records`, `expenses`, `platform_settings`) have no customer policy.

## Provisioning

Every client's assistant is built from one master template (`app/vapi/template.py`) with fenced,
idempotent creation and PATCH-and-verify updates (see `app/services/provisioning.py`). Phone
numbers are configured the same way (`app/services/phone_config.py`): pushed, read back,
verified; `needs_sync` until confirmed. The 15-minute sweep retries both.

## Data model

`businesses`, `business_members`, `business_hours`, `holiday_closures`, `services`,
`service_areas`, `faqs`, `assistants`, `phone_lines`, `calls`, `leads`, `lead_events`,
`packages`, `upgrade_requests`, `payment_records`, `expenses`, `platform_settings`,
`notifications`, `webhook_events`, `audit_logs`, `admin_users` (21). Stripe columns from the
earlier version remain unused (no destructive migration). Recordings are disabled and
transcripts are not stored.

## Public demo

Same release, separate deployment: Cloudflare Pages (`NEXT_PUBLIC_DEMO_MODE=true`) → Render
free (`DEMO_MODE=true`) → its own Supabase Free project. Isolation is physical (another
database and Auth instance), not a flag on shared data. In demo mode the API:

- seeds and periodically resets Houston Comfort HVAC (`app/services/demo.py`), restoring the
  published sign-ins and removing visitor-added MFA factors;
- serves `/public/demo` (sign-ins), `/api/demo/*` (voice status, live-voice session, simulated
  calls) and `/admin/api/demo/*` (spending controls, reset); all return 404 when `DEMO_MODE` is
  off;
- runs simulated calls through the real gate, tools (`vapi_tools._run`) and end-of-call
  processing, marked `sim-` and costing nothing;
- refuses phone-number assignment, invitations and Vapi provisioning for other businesses, and
  caps clients at 12;
- gates live browser voice by budget (Vapi-reported cost), per-day/per-IP limits, call length,
  an env-only ceiling and kill switch, and a 6-hour pause on credit errors.

Details: [demo-deployment.md](demo-deployment.md). Phone setup for real clients:
[phone-integration.md](phone-integration.md).
