# Phone integration (per client)

Each client keeps their existing business number. Nothing changes for their customers.

```
Customer dials the client's usual number
   └─ client's carrier forwards (all calls, or only busy/unanswered) ─▶ the client's BILEKSA number
        └─ Vapi asks BILEKSA (assistant-request): may the AI answer?
             ├─ yes → AI receptionist → tools → lead / callback / appointment / emergency
             │          └─ transfer allowed? → dials the client's designated transfer number
             └─ no (suspended, minutes used up, not ready) → forwarded to the client's direct line
   Every call, transfer, summary and lead is recorded in the client's dashboard.
```

## Configure a client (Admin → client → tabs)

1. **Business & routing**: transfer number (where the AI sends callers), fallback/direct line
   (used when the AI may not answer or a transfer fails), emergency number, and when transfers
   are allowed (in hours, after hours, emergencies after hours).
2. **Emergency**: the client's emergency rules (always callback, transfer, or by type).
3. **Phone & Vapi** → *Number source*:
   - **New Vapi number**: quickest. Vapi includes one free number per plan (more on paid
     packages, otherwise $2/month). Free Vapi numbers are inbound-only, so prefer Twilio for
     clients who want live transfers.
   - **Import a Twilio number** (recommended for paying clients): buy a local number in
     BILEKSA's Twilio account ($1.15/month), set `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN` on
     the backend, enter the number here. BILEKSA imports it into Vapi with no fixed assistant,
     the server URL and the client's fallback destination.
   Enter the client's business number, carrier and forwarding mode, then save. The panel shows
   the carrier-specific forwarding steps for the client.
4. The client sets up forwarding on their line; you press **Start test call** and call their
   business number within 15 minutes. The line turns *verified* only when that call actually
   reaches the BILEKSA number.

## Guarantees

- The AI never decides which business a call belongs to; the backend maps the Vapi number or
  assistant to the client.
- Over the minute limit, suspended or not ready: the call is forwarded to the client's line
  with no AI and no AI cost.
- If BILEKSA's server is unreachable, Vapi uses the number's fallback destination (the
  client's line), so calls are never dropped.
- Transfers that fail are recorded honestly and become a callback request.

The public demo blocks number assignment entirely; it runs voice in the browser.
