-- PUBLIC DEMO project only. Run once in the demo Supabase project's SQL editor after enabling
-- the pg_cron and pg_net extensions (Database -> Extensions). Replace the placeholders.
--
-- 1) Every 10 minutes: the normal recovery sweep. It also keeps the free API instance awake
--    (Render free sleeps after 15 minutes without traffic) and keeps this Supabase project
--    active (Free projects pause after 7 days of low activity).
-- 2) Every 6 hours: reset the demo data and the published demo sign-ins.
select cron.schedule(
  'bileksa-demo-sweep',
  '*/10 * * * *',
  $$
  select net.http_post(
    url := 'https://YOUR-DEMO-API.onrender.com/internal/sweep',
    headers := jsonb_build_object(
      'Authorization', 'Bearer YOUR_INTERNAL_SWEEP_SECRET',
      'Content-Type', 'application/json'
    ),
    body := '{}'::jsonb,
    timeout_milliseconds := 120000
  );
  $$
);

select cron.schedule(
  'bileksa-demo-reset',
  '7 */6 * * *',
  $$
  select net.http_post(
    url := 'https://YOUR-DEMO-API.onrender.com/internal/demo-reset',
    headers := jsonb_build_object(
      'Authorization', 'Bearer YOUR_INTERNAL_SWEEP_SECRET',
      'Content-Type', 'application/json'
    ),
    body := '{}'::jsonb,
    timeout_milliseconds := 120000
  );
  $$
);

-- Check:   select jobname, schedule from cron.job;
-- Runs:    select j.jobname, d.status, d.start_time from cron.job_run_details d
--            join cron.job j using (jobid) order by d.start_time desc limit 20;
-- HTTP:    select status_code, created from net._http_response order by created desc limit 10;
-- Remove:  select cron.unschedule('bileksa-demo-sweep'); select cron.unschedule('bileksa-demo-reset');
