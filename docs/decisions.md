# Decisions

## Product and architecture decisions (from the approved plan)

| # | Decision | Status |
| --- | --- | --- |
| D1 | Vapi Function tools with server URLs (not API Request tools) so requests carry Vapi's call object | Approved, implemented |
| D2 | Four Function tools; `log_call_outcome` dropped (the end-of-call report is the trusted outcome) | Approved, implemented |
| D3 | One shared dynamic `transferCall` (no destinations, no parameters); backend supplies the number | Approved, implemented |
| D4 | Destination numbers: Vapi-provided for the pilot; imported Twilio numbers before ~10 businesses | Open — implemented for Vapi numbers; Twilio import needs the cost comparison and live testing |
| D5 | Forwarding default: conditional (no-answer/busy) | Implemented as the default; owner can choose "all calls" |
| D6 | Stripe subscription + Billing Meters for overage | Approved, implemented |
| D7 | Dashboard data only through FastAPI; RLS as second layer | Approved, implemented |
| D8 | Recordings and transcripts off by default | Approved, implemented |
| D9 | Voice, model, transcriber | Open — configurable; defaults set; choose by listening tests |
| D10 | Recovery sweep from startup + 15-minute Supabase pg_cron | Approved, implemented (`supabase/pg_cron_sweep.sql`) |
| D11 | Provisioning fencing, create intent, settle window, duplicate deletion | Approved, implemented |
| D12 | Durable per-call billing events with reconciliation | Approved, implemented |
| D13 | Plan prices, included minutes, grace periods | Open — configurable; public site hides prices until approved |

## Technical decisions made during the build

| Decision | Reason |
| --- | --- |
| Stage 0 foundation recreated in this repository | The original Stage 0 repository (commit `8352e25`) lived in a different workspace that this build could not access. Same choices: Next.js 16, FastAPI with uv, Ruff, Alembic |
| No Stripe or Vapi SDKs; small `httpx` clients | Only a few endpoints are used; fewer dependencies and full control of timeouts and idempotency headers |
| Meter value = overage **seconds** | Avoids rounding disputes; price per second in Stripe |
| Callback and transfer data stored as columns (`leads`, `calls`) | One callback and one transfer attempt per call by design; keeps 14 tables |
| `subscription_status_changed_at` column (migration 0003) | Needed to measure the payment grace period; no new table |
| No component library (shadcn) | A dozen small Tailwind components cover the UI without generator tooling |
| Vapi call ownership confirmed with the Call API on first sight | Defence in depth beyond the authenticated payload; one request per call |
| Admin MFA required by default | Admin views show all businesses |
| E2E stand-ins for Supabase Auth, Vapi and Stripe | Workflows can be verified in a real browser without live accounts |
