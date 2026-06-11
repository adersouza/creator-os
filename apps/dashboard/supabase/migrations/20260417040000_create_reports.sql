-- juno33 Reports page — user-facing report configurations.
--
-- Distinct from `report_schedules` (narrow, already wired into weekly-reports
-- cron) and `shared_reports` (public-read frozen snapshots by token). This
-- table is the list the operator sees on /reports: PDF generation and
-- scheduling cron will read from here next.

CREATE TABLE IF NOT EXISTS public.reports (
  id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('scheduled', 'one-off')),
  cadence TEXT NOT NULL CHECK (cadence IN ('weekly', 'monthly', 'quarterly', 'one-off')),
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('active', 'paused', 'generated', 'draft')),
  network TEXT,
  recipients JSONB NOT NULL DEFAULT '[]'::jsonb,
  last_run_at TIMESTAMPTZ,
  next_run_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS reports_user_created_idx
  ON public.reports (user_id, created_at DESC);

-- Targets the "Active" filter + scheduled-run lookup.
CREATE INDEX IF NOT EXISTS reports_user_status_idx
  ON public.reports (user_id, status)
  WHERE status IN ('active', 'paused');

-- Cron will pull due rows by next_run_at.
CREATE INDEX IF NOT EXISTS reports_due_idx
  ON public.reports (next_run_at)
  WHERE status = 'active' AND next_run_at IS NOT NULL;

ALTER TABLE public.reports ENABLE ROW LEVEL SECURITY;

-- initPlan-safe form: wrap auth.uid() in SELECT so Postgres evaluates once.
DROP POLICY IF EXISTS "Users manage own reports" ON public.reports;
CREATE POLICY "Users manage own reports" ON public.reports
  FOR ALL
  USING ((SELECT auth.uid())::text = user_id)
  WITH CHECK ((SELECT auth.uid())::text = user_id);
