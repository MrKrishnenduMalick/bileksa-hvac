-- Decision D10: call the BILEKSA recovery sweep every 15 minutes from Supabase.
-- Run once in the Supabase SQL editor AFTER enabling the pg_cron and pg_net extensions
-- (Database → Extensions). Replace the two placeholders first. Store the secret in
-- Supabase Vault instead of plain text if your plan offers it.
select cron.schedule(
  'bileksa-sweep',
  '*/15 * * * *',
  $$
  select net.http_post(
    url := 'https://YOUR-BACKEND.up.railway.app/internal/sweep',
    headers := jsonb_build_object(
      'Authorization', 'Bearer YOUR_INTERNAL_SWEEP_SECRET',
      'Content-Type', 'application/json'
    ),
    body := '{}'::jsonb,
    timeout_milliseconds := 120000
  );
  $$
);

-- Check it is scheduled:      select * from cron.job;
-- See recent runs:            select * from cron.job_run_details order by start_time desc limit 10;
-- Remove it:                  select cron.unschedule('bileksa-sweep');
