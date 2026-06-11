CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ai_action_log_created_provider
  ON public.ai_action_log (created_at DESC, provider)
  WHERE cost_usd IS NOT NULL;
