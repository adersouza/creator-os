ALTER TABLE public.autopilot_runs
  DROP CONSTRAINT IF EXISTS autopilot_runs_run_type_check;

ALTER TABLE public.autopilot_runs
  ADD CONSTRAINT autopilot_runs_run_type_check
  CHECK (run_type IN ('queue_fill', 'publish', 'sync', 'reply_chain', 'auto_unpost'));
