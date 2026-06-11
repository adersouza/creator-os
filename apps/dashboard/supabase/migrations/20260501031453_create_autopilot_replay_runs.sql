-- Autopilot Phase 5: per-step replay logs.

CREATE TABLE IF NOT EXISTS public.autopilot_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  run_type TEXT NOT NULL CHECK (run_type IN ('queue_fill', 'publish', 'sync', 'reply_chain')),
  account_id TEXT REFERENCES public.accounts(id),
  post_id TEXT REFERENCES public.posts(id),
  status TEXT NOT NULL CHECK (status IN ('success', 'failed', 'partial', 'in_progress')),
  trigger TEXT,
  parent_run_id UUID REFERENCES public.autopilot_runs(id),
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ,
  metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS autopilot_runs_user_recent
  ON public.autopilot_runs (user_id, started_at DESC);

CREATE INDEX IF NOT EXISTS autopilot_runs_post
  ON public.autopilot_runs (post_id)
  WHERE post_id IS NOT NULL;

ALTER TABLE public.autopilot_runs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS autopilot_runs_select_own ON public.autopilot_runs;
CREATE POLICY autopilot_runs_select_own
  ON public.autopilot_runs
  FOR SELECT
  USING (auth.uid()::text = user_id);

DROP POLICY IF EXISTS autopilot_runs_service_all ON public.autopilot_runs;
CREATE POLICY autopilot_runs_service_all
  ON public.autopilot_runs
  FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

CREATE TABLE IF NOT EXISTS public.autopilot_run_steps (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id UUID NOT NULL REFERENCES public.autopilot_runs(id) ON DELETE CASCADE,
  step_index INT NOT NULL,
  step_name TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('success', 'failed', 'skipped')),
  inputs JSONB,
  outputs JSONB,
  error_message TEXT,
  duration_ms INT,
  started_at TIMESTAMPTZ NOT NULL,
  finished_at TIMESTAMPTZ,
  UNIQUE(run_id, step_index)
);

CREATE INDEX IF NOT EXISTS autopilot_run_steps_run
  ON public.autopilot_run_steps (run_id, step_index);

ALTER TABLE public.autopilot_run_steps ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS autopilot_run_steps_select_own ON public.autopilot_run_steps;
CREATE POLICY autopilot_run_steps_select_own
  ON public.autopilot_run_steps
  FOR SELECT
  USING (
    EXISTS (
      SELECT 1
      FROM public.autopilot_runs r
      WHERE r.id = autopilot_run_steps.run_id
        AND r.user_id = auth.uid()::text
    )
  );

DROP POLICY IF EXISTS autopilot_run_steps_service_all ON public.autopilot_run_steps;
CREATE POLICY autopilot_run_steps_service_all
  ON public.autopilot_run_steps
  FOR ALL
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');
