-- Watchdog alerts table — stores auto-poster health check results.
-- Written by the autoposter-watchdog cron every 30 minutes.

CREATE TABLE IF NOT EXISTS public.watchdog_alerts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  check_name TEXT NOT NULL,
  severity TEXT NOT NULL DEFAULT 'warn' CHECK (severity IN ('info', 'warn', 'error', 'critical')),
  message TEXT NOT NULL,
  details JSONB,
  resolved_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_watchdog_alerts_workspace ON public.watchdog_alerts(workspace_id);
CREATE INDEX IF NOT EXISTS idx_watchdog_alerts_created ON public.watchdog_alerts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_watchdog_alerts_unresolved ON public.watchdog_alerts(workspace_id, resolved_at)
  WHERE resolved_at IS NULL;

ALTER TABLE public.watchdog_alerts ENABLE ROW LEVEL SECURITY;

CREATE POLICY "watchdog_alerts_owner" ON public.watchdog_alerts
  FOR ALL USING (
    workspace_id IN (SELECT id FROM workspaces WHERE owner_id = auth.uid()::text)
  );

-- Discord webhook URL on auto_post_config (per-workspace)
ALTER TABLE public.auto_post_config
  ADD COLUMN IF NOT EXISTS discord_webhook_url TEXT;

COMMENT ON COLUMN public.auto_post_config.discord_webhook_url IS
  'Per-workspace Discord webhook URL for watchdog alerts. Falls back to DISCORD_ALERT_WEBHOOK_URL env var.';
