# Hosting choice and monthly costs

Prices as published in November 2026, in USD. They change; re-check before quoting a client.
The admin **Costs & profit** page uses the assumptions you set there, so update them when your
real bills arrive.

## Public demo: ₹0 per month

| Piece | Service | Cost |
| --- | --- | --- |
| Website, SSL, DNS | Cloudflare Pages + Cloudflare DNS | $0 |
| API | Render free web service | $0 |
| Database + sign-in + scheduler | Supabase Free (separate demo project) | $0 |
| Source + CI | GitHub (private repo, Actions free minutes) | $0 |
| Live voice | Vapi free credits ($5, once), no card on file | $0 |
| Domain | `*.pages.dev` / `*.onrender.com`, or a domain you already own | $0 (a new domain is ~$10/year) |

When the Vapi credits are used up the demo keeps working with the simulated calls; nothing is
charged. Adding live voice again later means topping up Vapi (pay-as-you-go, ~$0.10–0.16/min).
See [demo-deployment.md](demo-deployment.md) for the limits of these free plans.

## Paying clients: don't use free hosting

Free plans sleep, pause and carry no uptime promise; a client's phone line can't wait a minute
for a server to wake. Recommended, cheapest setup that is still reliable:

| Piece | Recommended | Monthly | Why this one |
| --- | --- | --- | --- |
| Frontend | Cloudflare Pages | $0 | Static site, global CDN, free SSL; nothing to keep awake |
| API | Railway Hobby (already configured: `backend/railway.json`) | ~$5–10 (Hobby $5 includes $5 usage) | Always on, release-step migrations, health checks, restarts |
| Database + Auth | Supabase Pro | $25 | No pausing, daily backups (PITR add-on available), more headroom |
| Voice platform | Vapi pay-as-you-go → Core ($29) once you need >4 simultaneous calls | $0 → $29 | Free plan allows 4 concurrent calls across **all** clients |
| Phone numbers | Twilio numbers imported into Vapi | $1.15 per client | Cheaper than Vapi numbers ($2) and can dial out for transfers |
| Email alerts (optional) | Any SMTP (e.g. Resend/Brevo free tiers) | $0 | Notifications show in the dashboards anyway |
| Domain | Cloudflare Registrar | ~$1 | At-cost renewals |

Alternatives considered: Render Starter ($7, always on) is equivalent to Railway for the API;
Fly.io and Cloud Run are fine but add setup; Vercel Hobby forbids commercial use, so the
production frontend moves to Cloudflare Pages (Vercel Pro, $20, also works).

**Platform total:** about **$32–37/month** with up to ~4 simultaneous calls, about
**$61–66/month** once you add Vapi Core. This is shared by all clients.

## Cost per client

Per minute of AI-answered call (worst-case estimate): Vapi platform $0.05 + speech-to-text,
LLM and voice ≈ $0.05–0.10 + Twilio inbound $0.0085 ≈ **$0.11–0.16**. The app's default cost
assumption is $0.15 + $0.01 telephony = **$0.16/min**, i.e. the pessimistic end. Using
`gpt-4.1-mini` and a Vapi/Deepgram voice instead of `gpt-4.1` + ElevenLabs moves you toward the
low end; decide by listening tests.

Transfers to the client's own phone add a Twilio outbound leg (~$0.014/min while connected).
Forwarded calls from the client's line usually cost the client nothing extra on business plans
(check with their carrier).

Worst case: every included minute used, $0.16/min, $1.15 number, platform $63/month shared by
5 clients ($12.60 each):

| Package | Price | Minutes | Voice + number | Platform share | Total cost | Margin |
| --- | --- | --- | --- | --- | --- | --- |
| Starter | $199 | 300 | $49.15 | $12.60 | $61.75 | $137.25 (69%) |
| Professional | $399 | 700 | $113.15 | $12.60 | $125.75 | $273.25 (68%) |
| Premium | $699 | 1,500 | $241.15 | $12.60 | $253.75 | $445.25 (64%) |

At 20 clients the platform share drops to about $3/client. Typical clients use 40–70% of their
minutes, so real margins are higher. The hard minute limit means a client can never cost more
than their package's minutes: after the limit, calls are forwarded without the AI.

The app's default "fixed monthly per client" of $41 is deliberately conservative (it covers
platform share, number, support time and payment fees). Lower it on **Costs & profit** once you
know your real numbers. If you later take card payments, add ~2.9% + $0.30 per payment.

## What would break profitability

- Long calls on gpt-4.1 + ElevenLabs at the top of the range: keep the cost assumption at
  $0.16 until real invoices say otherwise.
- Many clients on the free Vapi plan: calls beyond 4 at once get busy signals; move to Core.
- Selling Premium to a very high-volume client without watching Admin → Usage & limits.
