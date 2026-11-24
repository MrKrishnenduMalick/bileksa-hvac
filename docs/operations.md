# Operations runbook

## Monitoring

| What | Where | Alert when |
| --- | --- | --- |
| Backend up and DB reachable | `GET /health/ready` (uptime monitor) | Non-200 for 2 minutes |
| Crashes / restarts | Railway service alerts | Any restart loop |
| Tool failures, provisioning/phone-sync errors, refused security events | Admin → Notifications and Errors | Check daily; `vapi_call_binding_mismatch`, `phone_sync_error`, `duplicate_assistant_linked`, `vapi_unreachable` need action |
| Clients near or at their limit, upgrade requests | Admin → Usage & limits, Upgrade requests, Notifications | Contact the client |
| Recovery sweep | Supabase `cron.job_run_details` | Failed runs |
| Revenue, estimated cost, gross profit | Admin → Costs & profit | Margin below target |
| Vapi concurrency | Vapi dashboard | Peak near the purchased line count |

Logs are plain text on stdout (Railway). Neither logs nor the audit log contain secrets or full
phone numbers.

## Common tasks

**A client's assistant is not verified.** Admin → client → Phone & Vapi. Read the error, fix
the cause (Vapi key, tools missing in Admin → Vapi tools), then **Re-sync assistant**. Retrying is
always safe: fenced provisioning never creates a second mapped assistant. Until it is verified,
calls are forwarded to the client's direct line and BILEKSA is notified.

**Phone routing "not synced".** Admin → client → Phone & Vapi → **Sync routing to Vapi**. The
sweep also retries every 15 minutes. While unsynced, the number may still point at old settings.

**Changing the master template** (voice, model, prompt, safety text, tools). Edit
`app/vapi/template.py`, bump `TEMPLATE_VERSION`, deploy, then Admin → Vapi tools → **Sync tools**.
The sweep PATCHes and verifies every assistant.

**Client reached the limit.** They and BILEKSA were notified. Record payment, then change the
package, raise the limit or renew the period (password). AI answering resumes on the next call.

**Customer reports a wrong number spoken.** Call history shows "Check numbers" for amounts the
receptionist said that neither a tool nor the approved price list provided.

**Transfer "attempted (not confirmed)".** In blind mode Vapi cannot confirm that anyone
answered; the call summary tells the owner to call back if needed. Warm mode reports
"connected" or "failed" (failed transfers get an automatic callback).

**Emails not arriving.** Admin → Costs & profit shows whether email is configured; each
notification shows its email status (pending / sent / failed / skipped).

## Incidents

- **Backend down**: new calls are forwarded by Vapi to each number's fallback destination (the
  client's direct line). Calls already with the AI still give the safety instructions and
  collect details; tools answer `success: false`; leads are recovered from Vapi's call records
  by the sweep once the backend is back.
- **Vapi outage**: with conditional forwarding the owner's phone rings first; post a status note.
- **Suspected data exposure**: check Admin → Audit log for `vapi_*` security events and
  `admin_support_view` entries; rotate `VAPI_WEBHOOK_SECRET` (update the Vapi credential and
  Railway together) and `INTERNAL_SWEEP_SECRET`.

## Secret rotation

| Secret | How |
| --- | --- |
| `VAPI_WEBHOOK_SECRET` | Edit the Vapi Custom Credential token and the Railway variable together (brief refusal window; do it off-peak) |
| `INTERNAL_SWEEP_SECRET` | Update Railway, then re-run `supabase/pg_cron_sweep.sql` (unschedule first) |
| `SUPABASE_SERVICE_ROLE_KEY` | Roll in Supabase → API settings, update Railway |
| Supabase DB password | Reset in Supabase, update `DATABASE_URL` |

## Backups

Supabase daily backups / PITR. Quarterly, restore the latest backup to a scratch project and
run `scripts/backup_restore_check.sh <restored-db-url> <admin-url>` against a dump of
production to confirm row counts, RLS and policies survive.
