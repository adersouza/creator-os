CREATE TABLE IF NOT EXISTS public.account_health_signals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id TEXT NOT NULL REFERENCES public.accounts(id) ON DELETE CASCADE,
  signal_type TEXT NOT NULL CHECK (signal_type IN ('engagement_spike','reach_anomaly','shadowban_risk','token_expiring','rate_limit')),
  severity TEXT NOT NULL CHECK (severity IN ('good','warn','critical')),
  metadata JSONB DEFAULT '{}'::jsonb,
  detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_account_health_active
  ON public.account_health_signals(account_id, severity, resolved_at)
  WHERE resolved_at IS NULL;

ALTER TABLE public.account_health_signals ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users view own account health signals" ON public.account_health_signals;
CREATE POLICY "Users view own account health signals"
  ON public.account_health_signals
  FOR SELECT
  USING (
    EXISTS (
      SELECT 1
      FROM public.accounts a
      WHERE a.id = account_health_signals.account_id
        AND a.user_id = auth.uid()::text
    )
  );

DROP POLICY IF EXISTS "Service role manages account health signals" ON public.account_health_signals;
CREATE POLICY "Service role manages account health signals"
  ON public.account_health_signals
  FOR ALL
  USING ((auth.jwt()->>'role') = 'service_role')
  WITH CHECK ((auth.jwt()->>'role') = 'service_role');
