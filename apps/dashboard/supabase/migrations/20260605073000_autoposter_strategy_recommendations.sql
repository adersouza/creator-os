BEGIN;

CREATE TABLE IF NOT EXISTS public.autoposter_strategy_recommendations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id TEXT NOT NULL,
  group_id TEXT,
  account_id TEXT,
  pattern_type TEXT NOT NULL,
  pattern_value TEXT NOT NULL,
  recommendation TEXT NOT NULL,
  confidence NUMERIC NOT NULL DEFAULT 0,
  reason TEXT NOT NULL,
  metric_basis JSONB NOT NULL DEFAULT '{}'::jsonb,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT autoposter_strategy_recommendation_check
    CHECK (recommendation IN ('increase', 'decrease', 'test', 'avoid')),
  CONSTRAINT autoposter_strategy_confidence_check
    CHECK (confidence >= 0 AND confidence <= 1),
  CONSTRAINT autoposter_strategy_pattern_type_check
    CHECK (pattern_type IN (
      'hook_type',
      'topic_label',
      'format_type',
      'emotional_frame',
      'reply_mechanism',
      'content_length_bucket',
      'media_style',
      'posting_hour'
    ))
);

CREATE UNIQUE INDEX IF NOT EXISTS autoposter_strategy_recommendations_unique
  ON public.autoposter_strategy_recommendations(
    workspace_id,
    COALESCE(group_id, ''),
    COALESCE(account_id, ''),
    pattern_type,
    pattern_value,
    recommendation
  );

CREATE INDEX IF NOT EXISTS idx_autoposter_strategy_active_scope
  ON public.autoposter_strategy_recommendations(
    workspace_id,
    group_id,
    account_id,
    expires_at DESC,
    confidence DESC
  );

CREATE OR REPLACE FUNCTION public.touch_autoposter_strategy_recommendations()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_autoposter_strategy_recommendations_updated_at
  ON public.autoposter_strategy_recommendations;
CREATE TRIGGER trg_autoposter_strategy_recommendations_updated_at
  BEFORE UPDATE ON public.autoposter_strategy_recommendations
  FOR EACH ROW
  EXECUTE FUNCTION public.touch_autoposter_strategy_recommendations();

ALTER TABLE public.autoposter_strategy_recommendations ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Workspace members can view autoposter strategy recommendations"
  ON public.autoposter_strategy_recommendations;
CREATE POLICY "Workspace members can view autoposter strategy recommendations"
  ON public.autoposter_strategy_recommendations
  FOR SELECT
  TO authenticated
  USING (
    EXISTS (
      SELECT 1
      FROM public.workspace_members wm
      WHERE wm.workspace_id = autoposter_strategy_recommendations.workspace_id
        AND wm.user_id = (SELECT auth.uid())::text
    )
  );

DROP POLICY IF EXISTS "Service role can manage autoposter strategy recommendations"
  ON public.autoposter_strategy_recommendations;
CREATE POLICY "Service role can manage autoposter strategy recommendations"
  ON public.autoposter_strategy_recommendations
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

COMMIT;
