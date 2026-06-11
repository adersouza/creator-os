ALTER TABLE public.reports
  ADD COLUMN IF NOT EXISTS config JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS last_sent_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS public.report_send_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  report_id TEXT NOT NULL REFERENCES public.reports(id) ON DELETE CASCADE,
  recipients TEXT[] NOT NULL DEFAULT '{}',
  sent_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  status TEXT NOT NULL CHECK (status IN ('sent', 'failed', 'skipped')),
  error TEXT
);

CREATE INDEX IF NOT EXISTS idx_report_send_log_report
  ON public.report_send_log(report_id, sent_at DESC);

ALTER TABLE public.report_send_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users view own report send log"
  ON public.report_send_log
  FOR SELECT
  USING (
    EXISTS (
      SELECT 1
      FROM public.reports r
      WHERE r.id = report_send_log.report_id
        AND r.user_id = (SELECT auth.uid())::text
    )
  );

CREATE POLICY "Service role manages report send log"
  ON public.report_send_log
  FOR ALL
  USING ((auth.jwt()->>'role') = 'service_role')
  WITH CHECK ((auth.jwt()->>'role') = 'service_role');
