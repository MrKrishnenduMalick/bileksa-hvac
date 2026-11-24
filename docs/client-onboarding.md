# Onboarding a new HVAC client

Everything happens in the admin panel (`/admin`). The client never configures anything
themselves; they get a read-only dashboard. Each step below matches the onboarding checklist
on the client's Overview tab.

| # | Step | Where | Notes |
| --- | --- | --- | --- |
| 1 | **Create client** | Clients → Create a client | Name, contact email/phone, time zone. A Vapi assistant is provisioned from the master template automatically (Phone & Vapi tab shows its state) |
| 2 | **Business information** | Business & routing | Address, website, owner notification email |
| 3 | **Services and service areas** | Services, Service areas | Only listed services and approved price ranges are ever quoted. ZIP codes decide coverage |
| — | Hours and holidays | Hours | Used for "are you open?" and transfer rules |
| 4 | **Phone numbers and transfers** | Business & routing | Transfer number = the client's **direct** line (never the number that forwards to the AI). Transfer mode: blind (default, most reliable) or warm (returns the caller to the AI if nobody answers; verify with a live test first) |
| 5 | **Emergency and fallback rules** | Business & routing, Emergency | Emergency line (tried first for emergencies), fallback number (backup for transfers and for calls when the AI is off), unavailable-call message. Per-category: transfer or callback, approved extra instructions; custom categories need approved instructions |
| 6 | **FAQs and policies** | FAQs | The AI repeats these answers word for word; unanswered questions become callbacks |
| 7 | **Vapi assistant and tools** | Phone & Vapi; Admin → Vapi tools | Assistant must be "Verified" on the current template version. Tools are global; sync them once per deployment |
| 8 | **Package and minute limit** | Overview → Package, minutes and service | Assign Starter/Professional/Premium (password confirmation). Do this **before** the test call: with 0 minutes, calls are forwarded without the AI |
| 9 | **Phone number and test call** | Phone & Vapi | Enter the client's business number and carrier → **Assign Vapi number** (routing is synced automatically). Give the client the forwarding steps shown. **Start test call**, call the business number within 15 minutes; the line turns "Verified" when the call arrives |
| 10 | **Activate the client** | Overview → Activate client | Password confirmation. A fresh usage period starts now (test-call minutes don't count) |
| — | Invite the owner | Overview → Client accounts | The owner receives a Supabase invitation email, sets a password and signs in to `/app` |

## After go-live

- **Payments** (outside the app): record each one in the client's Payments tab (amount, type,
  date, status, period, notes). Setup/build fees are never shown to the client.
- **Renewal**: after recording the month's payment, press **Renew period** (password). If a
  period passes without renewal, usage keeps counting against the same limit; there is no free
  reset and no overage.
- **Upgrade requests**: the client clicks Request Upgrade → you get a notification and the
  request appears in Upgrade requests and on the client's Overview. Contact the client, verify
  payment, mark it "Payment verified", then **Activate requested package** (password).
- **Limit reached**: the client and BILEKSA are notified at 80 % and at 100 %. At 100 % new calls
  are forwarded to the direct line → fallback number → unavailable message; calls in progress
  finish. Raise the limit, change package or renew to restore AI answering immediately.
- **Suspend / restore**: from the Overview tab (password). Suspended clients' calls are forwarded
  without the AI.
- **Costs & profit**: monthly per-client revenue (recorded payments), estimated Vapi and
  telephony cost, fixed allocation, other expenses and gross profit. Edit the assumptions there.
