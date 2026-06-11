CREATE TABLE IF NOT EXISTS public.ai_action_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  account_id TEXT REFERENCES public.accounts(id),
  surface TEXT NOT NULL CHECK (surface IN ('composer','inbox','autopilot','analytics')),
  action_type TEXT NOT NULL,
  input_text TEXT,
  output_text TEXT,
  model_used TEXT,
  provider TEXT,
  latency_ms INT,
  tokens_in INT,
  tokens_out INT,
  cost_usd NUMERIC(10,6),
  metadata JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ai_action_log_user_recent ON public.ai_action_log(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_action_log_surface ON public.ai_action_log(surface, action_type, created_at DESC);
ALTER TABLE public.ai_action_log ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Users view own ai logs" ON public.ai_action_log;
CREATE POLICY "Users view own ai logs" ON public.ai_action_log FOR SELECT USING (auth.uid()::text = user_id);
DROP POLICY IF EXISTS "Service role writes ai logs" ON public.ai_action_log;
CREATE POLICY "Service role writes ai logs" ON public.ai_action_log FOR ALL USING ((auth.jwt()->>'role') = 'service_role') WITH CHECK ((auth.jwt()->>'role') = 'service_role');
