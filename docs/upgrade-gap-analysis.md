# BILEKSA final upgrade: repository audit and gap analysis

Spec: `BILEKSA — FINAL AI RECEPTIONIST UPGRADE` (supersedes the earlier "master upgrade" brief and
its audit document; that brief's Stripe wallet, invitations-CRM and document-ingestion plan is
dropped).

Baseline before any change: commit `5208b56`, 86/86 backend tests passing (`uv run pytest`).

## What works today (kept)

| Area | State |
| --- | --- |
| Vapi integration | Native Vapi function tools created with `POST /tool`, attached by `model.toolIds`; native `transferCall` (dynamic, number chosen server-side) and `endCall`. Backend only executes. Compliant with spec §2 |
| Tenant isolation | Business resolved only from Vapi's call object → `assistants` mapping; tool arguments like `business_id` ignored; call bound to one business; RLS on every table; isolation tests |
| Provisioning | Fenced, idempotent assistant creation/updates from one master template; recovery sweep |
| Leads/callbacks | One lead per call, idempotent updates, number read-back confirmation, after-call fallback from Vapi structured data, reconciliation of missing end-of-call reports from Vapi's API |
| Emergency safety | Fixed safety block in the prompt (given before any tool, even if tools fail) |
| Auth | Supabase JWT (HS256/JWKS), admin role table, admin MFA (aal2), rate limits, body caps, audit log |
| Dashboards | Customer overview, calls, leads, callbacks; admin businesses, errors, usage, audit |

## Gaps against the spec

| Spec | Gap | Fix |
| --- | --- | --- |
| §4 Check Service Area | Only a topic inside `get_business_information` | Dedicated `check_service_area` tool |
| §4 Appointment handling | Missing | `request_appointment` tool: records a request; **never** reports a booking (no booking integration exists) |
| §4 Structured results | Mixed shapes (`{"error": ...}`) | Every tool returns `success: true/false` with `say`/`next` |
| §3 Lead fields | No equipment type, new/existing customer, preferred appointment, notes | Added |
| §3/§15 Duplicate leads | One lead per call only; a caller who calls back creates a second lead | Repeat calls from the same number within 12 h reuse the open lead |
| §3 Call summaries / owner notifications | Summary not stored; no notifications at all | Store Vapi's summary; notification outbox (dashboard + optional SMTP email) |
| §5 Transfer fallback | One transfer number, no fallback | Transfer → fallback number on second attempt → callback; optional warm-transfer mode that returns the caller to the AI when no one answers |
| §5 Vapi/AI unavailable | No routing when our server is down | Vapi phone-number `fallbackDestination` (Vapi forwards there if our server doesn't answer) + incident logging/notification |
| §6 Emergency rules per client | Fixed categories only; not configurable; no owner alert | Per-client categories, approved extra instructions, emergency number; owner notified immediately |
| §7 Client dashboard | Self-serve setup/billing pages; no usage/packages/upgrade | Simplified: Overview, Calls, Leads, Callbacks & appointments, Usage, Packages (request upgrade), read-only Business info |
| §8 Admin client management | Admin can only view; customers self-register and self-configure | Admin creates and configures clients (profile, services, areas, hours, phones, transfers, emergency, FAQs, Vapi); invites the client owner |
| §8/§9 Packages | Single Stripe plan | `packages` table (Starter/Professional/Premium, admin-editable price/minutes/features) |
| §8/§12 Payments | Stripe Checkout/Portal/meters | **Removed** (no gateway). Admin records payments manually |
| §10 Hard minute limits | Usage beyond included minutes is billed as overage | Hard limit checked per incoming call (Vapi `assistant-request`): over limit → forward to business direct line → fallback number → configured message. Existing calls finish. `limit_reached` status, notifications |
| §11 Password confirmation | Missing | Package/limit/renewal/suspend/restore/activate actions require the admin's password, verified server-side with Supabase Auth; full before/after audit |
| §12 Upgrade requests | Missing | Client request → admin notified → admin activates (password) |
| §13 Cost tracking | Revenue from Stripe, actual Vapi cost only | Configurable estimates ($0.15 Vapi + $0.01 telephony per minute, $41 fixed per client per month), manual revenue, other expenses, gross profit |
| Public site | Public sign-up and pricing pages | Removed; clients are created by BILEKSA |

## Broken or risky today

1. **Self-registration** lets anyone create a tenant and an assistant (cost exposure). Removed.
2. **Automatic overage billing** contradicts the hard-limit rule. Removed.
3. **No server-side call gate**: the phone number points straight at the assistant, so nothing can
   stop a call. Fixed by moving numbers to `assistant-request` mode.
4. **Transfer loop risk**: only the transfer number was checked against the forwarded line; fallback
   destinations now get the same check.

## Decisions taken (no answer needed to proceed; easy to change)

- Limit-reached and suspended calls forward to the client's **direct line** (transfer number), not
  the "business number", because the business number forwards into the AI and would loop.
- When a usage period ends and the admin hasn't renewed, usage keeps counting against the same
  limit (no free reset). Admin renews after recording payment.
- `$41` fixed allocation is applied **per launched client per month** (configurable). If it is
  meant as one platform-wide figure, set it per client to `41 / number of clients`.
- Calls already in progress when the limit is reached finish normally (bounded by the 20-minute
  maximum call length).
- Stripe columns stay in the database (no destructive migration); the code paths are removed.
- Client accounts are created by admin invitation through Supabase Auth (backend-only service key).

## Requires live configuration (cannot be verified here)

Vapi API key and credential, Supabase service-role and anon keys, SMTP credentials, and a real
phone test of: assistant-request routing, `fallbackDestination`, warm-transfer fallback. See
`docs/external-verification.md`.
