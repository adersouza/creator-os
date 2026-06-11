CREATE TABLE IF NOT EXISTS public.portfolio_account_health (
  account_id TEXT PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  account_group_id TEXT REFERENCES account_groups(id),
  days_of_content INT,
  health_tier TEXT CHECK (health_tier IN ('good','warn','critical')),
  posts_next_7d INT,
  empty_days_next_7d INT,
  last_published_at TIMESTAMPTZ,
  computed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_portfolio_health_user
  ON public.portfolio_account_health(user_id, health_tier);

ALTER TABLE public.portfolio_account_health ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users view own portfolio health" ON public.portfolio_account_health;
CREATE POLICY "Users view own portfolio health"
  ON public.portfolio_account_health
  FOR SELECT
  USING (auth.uid()::text = user_id);

DROP POLICY IF EXISTS "Service role manages health" ON public.portfolio_account_health;
CREATE POLICY "Service role manages health"
  ON public.portfolio_account_health
  FOR ALL
  USING ((auth.jwt()->>'role') = 'service_role')
  WITH CHECK ((auth.jwt()->>'role') = 'service_role');

CREATE TABLE IF NOT EXISTS public.calendar_reschedule_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  batch_id UUID NOT NULL DEFAULT gen_random_uuid(),
  user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  prev_scheduled_at TIMESTAMPTZ,
  new_scheduled_at TIMESTAMPTZ,
  reason TEXT,
  triggered_by TEXT CHECK (triggered_by IN ('user','ai_nudge','autopilot','queue_rebalance')),
  reverted_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_reschedule_log_post
  ON public.calendar_reschedule_log(post_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_reschedule_log_user_recent
  ON public.calendar_reschedule_log(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_reschedule_log_batch
  ON public.calendar_reschedule_log(batch_id, created_at DESC);

ALTER TABLE public.calendar_reschedule_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users manage own reschedule log" ON public.calendar_reschedule_log;
CREATE POLICY "Users manage own reschedule log"
  ON public.calendar_reschedule_log
  FOR ALL
  USING (auth.uid()::text = user_id)
  WITH CHECK (auth.uid()::text = user_id);
