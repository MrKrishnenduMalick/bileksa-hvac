# Final audit and deployment round (23 November 2026)

Scope: audit the finished 2.0 product for deployment, fix what blocks a real public demo and
real client deployments, without rebuilding. Results of every check are in
[testing.md](testing.md).

## Working (verified, kept as is)

Managed-service flow end to end: admin-only clients, invitations, packages with hard minute
limits at the `assistant-request` gate, password-confirmed service actions, upgrades and manual
payments, cost tracking, per-client emergency rules, transfer → backup → callback, tools v2,
notifications, tenant isolation (server-side mapping + RLS), provisioning idempotency. 17/17
browser workflows and the full backend suite pass.

## Broken or blocking deployment (fixed)

| Problem | Fix |
| --- | --- |
| Microphone blocked by `Permissions-Policy`; CSP had no Vapi/Daily hosts → browser voice impossible | Per-build headers; voice hosts and microphone only on the demo build |
| Security headers defined in `next.config` `headers()`; ignored by static hosting | `_headers` generated at build for Cloudflare Pages |
| Frontend needed a Node server (dynamic routes `/admin/clients/[id]`, `/app/leads/[id]`) | Static export; detail pages are `/admin/client?id=` and `/app/lead?id=` |
| Leftover Stripe `form-action` in the CSP | Removed |
| Twilio-imported numbers saved Vapi's echo instead of the imported number | Destination is the imported number when the provider is Twilio |
| No way to run migrations on hosts without a release step | `RUN_MIGRATIONS_ON_START=true` in the container command |
| Deployment docs and Vapi facts out of date (Vapi now: $5 one-time credits, 4 concurrent calls and 1 free number on pay-as-you-go) | Docs corrected; costs re-done |
| E2E runner could test against a stale server from an earlier run | Cleanup kills the static server by its port arguments |

## Missing (added)

- **Public demo** (Houston Comfort HVAC): seeded realistic data, published sign-ins, 6-hourly
  reset, live browser voice with a spending guard, labelled simulated calls through the real
  pipeline, admin demo controls, guardrails (no forwarding, no invites, client cap).
- **Twilio numbers per client** (admin → Phone & Vapi → Number source).
- Deployment configs: `render.yaml`, `supabase/demo_cron.sql`, `.env.demo.example` files,
  Cloudflare Pages settings.
- Docs: [demo-deployment.md](demo-deployment.md), [costs.md](costs.md),
  [phone-integration.md](phone-integration.md).

## Security

Fixed findings are listed in [security.md](security.md#deployment-round-findings-fixed). No
private key, service-role key or secret reaches the frontend (secret scan passes; only the Vapi
**public** key is sent to the browser, on the demo, and only after a signed-in reservation).

## Not done here, and why

- **Deployment and a live URL.** This workspace has no access to your Cloudflare, Render,
  Supabase or Vapi accounts, and no GitHub repository for the project exists yet. Everything is
  configured to deploy from GitHub in the steps in [demo-deployment.md](demo-deployment.md).
- Live calls, live browser voice, real provider responses: see
  [external-verification.md](external-verification.md).
