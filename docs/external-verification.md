# What still needs real accounts, live calls or experts

Everything below was built and tested against stand-ins that follow each provider's documented
API. These items can only be confirmed with real accounts, real phone calls or professional
review. Do them in **staging** first.

## Needs real accounts (credentials you provide)

| Item | How to confirm |
| --- | --- |
| Supabase Auth: admin invite email (`/auth/v1/invite` with the service-role key), invite link → `/reset-password`, JWKS tokens, MFA (`aal2`) | Invite an owner from the admin panel; they set a password and sign in |
| Admin password re-verification (`/auth/v1/token?grant_type=password` with the anon key, then logout) | A package change with the right and a wrong password |
| RLS on Supabase itself (role `postgres` can `SET ROLE authenticated`) | Open the dashboard; `GET /api/business` must succeed |
| `pg_cron` + `pg_net` on your Supabase plan (A14) | `select * from cron.job_run_details` shows successful runs |
| Vapi: tool create/update by name (`GET/PATCH /tool`), assistant create/verify/PATCH, metadata (A1, A5) | Admin → Vapi tools → Sync; create a client; its assistant shows "Verified" |
| Vapi phone number with no `assistantId`, `server.url` + `credentialId`, `fallbackDestination` (`PATCH /phone-number`) | Admin → Phone & Vapi shows "Routing synced"; check the number in the Vapi dashboard |
| `assistant-request` → `{"assistantId"}` answers with the AI; `{"destination"}` forwards without AI; `{"error"}` is spoken | Live calls with the client active, over the limit, and with no forwarding numbers |
| Backend down/503 on `assistant-request` → Vapi uses `fallbackDestination` (community reports vary; must be tested) | Stop the backend and call |
| Tool/event payloads for gated calls include `call.assistantId` and/or `call.phoneNumberId` | First real tool call succeeds (either id is accepted) |
| Vapi credential sent on tool and event requests (A2) | First real tool call succeeds; a wrong token is refused |
| Vapi tool-call payload includes `call.assistantId` (A1) | Logged first request |
| End-of-call report fields: duration, cost, structured data (A7) | First real call shows minutes, cost and lead |
| Whether Vapi retries failed tool calls (A6) | Observe during a backend restart drill |
| SMTP delivery from Railway (paid plan needed for outbound SMTP) | Trigger an emergency test call; the owner email arrives |
| Docker image build on Railway | First deploy (no Docker daemon was available during the build; the same commands were verified natively) |
| GitHub Actions workflows | First push to GitHub |
| Twilio number import into Vapi (`POST /phone-number` with `provider: twilio`) and transfers dialling out through it | Import one number for a staging client; call it; let the AI transfer |
| Public demo: Render free deploy with `RUN_MIGRATIONS_ON_START`, Cloudflare Pages build + `_headers`, demo seeding against real Supabase Auth admin API | Follow [demo-deployment.md](demo-deployment.md); `/demo` sign-ins work |
| Live browser voice: Vapi Web SDK with a restricted public key under the site CSP (Vapi + Daily hosts), microphone permission, `maxDurationSeconds`, cost in the end-of-call report | One short browser call on the demo; Demo controls shows its cost |
| Vapi's error text when credits run out (the demo pauses live voice on words like "credit", "balance", "wallet", "payment") | Let the demo org run out of credits; the next call should pause live voice |

## Needs live telephony testing

| Item | Plan ref |
| --- | --- |
| Transfer outcomes: blind transfer stays "attempted (not confirmed)"; warm transfer (`warm-transfer-experimental` + `transferAssistant` + `fallbackPlan`) returning the caller to the AI and the ended reasons used to mark "failed"/"connected" | A4 |
| Original caller ID survives carrier forwarding (AT&T, Verizon, T-Mobile, Comcast Business) | A8 |
| Carrier forwarding codes in the setup guide (`*71`, `*72`, `**004*`, `**21*`) | A9 |
| Test-call verification on a real forwarded line | Phase 2 |
| Real latency of tool calls on Railway (target < 500 ms p95) | Phase 2 |
| Number limits, concurrency and real per-minute costs; Twilio import decision | A10, D4 |
| Listening tests to choose voice, model and transcriber | D9 |
| All scenarios in [live-call-tests.md](live-call-tests.md): normal, difficult (accent, noise, interruptions, angry caller, corrections), emergencies, failures | Final spec §15 |

## Needs professional review

| Item | Who |
| --- | --- |
| Privacy policy, terms of service, AI disclosure, recording/transcript consent, data retention (pages are placeholders marked for legal review) | Lawyer (A12) |
| Emergency safety wording in `backend/app/vapi/template.py` | HVAC or safety professional (A13) |
| Package prices, minutes and features (seeded from the spec; editable in Admin → Packages); cost assumptions | You |
| Independent penetration test | Security firm (recommended before scale) |
