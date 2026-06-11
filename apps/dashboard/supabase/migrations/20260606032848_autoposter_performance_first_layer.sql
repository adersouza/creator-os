BEGIN;

ALTER TABLE IF EXISTS public.autoposter_strategy_recommendations
  DROP CONSTRAINT IF EXISTS autoposter_strategy_pattern_type_check;

ALTER TABLE IF EXISTS public.autoposter_strategy_recommendations
  ADD CONSTRAINT autoposter_strategy_pattern_type_check
  CHECK (pattern_type IN (
    'hook_type',
    'topic_label',
    'format_type',
    'emotional_frame',
    'reply_mechanism',
    'content_length_bucket',
    'media_style',
    'posting_hour',
    'content_archetype',
    'shape_id',
    'source_type',
    'winner_clone',
    'account_strategy'
  ));

ALTER TABLE IF EXISTS public.account_autoposter_state
  ADD COLUMN IF NOT EXISTS avg_views_24h_30d NUMERIC,
  ADD COLUMN IF NOT EXISTS median_views_24h_30d NUMERIC,
  ADD COLUMN IF NOT EXISTS posts_above_100_views_rate NUMERIC,
  ADD COLUMN IF NOT EXISTS profile_click_rate_30d NUMERIC,
  ADD COLUMN IF NOT EXISTS revenue_per_post_30d NUMERIC,
  ADD COLUMN IF NOT EXISTS recommended_posts_per_day NUMERIC,
  ADD COLUMN IF NOT EXISTS recommended_strategy_mode TEXT,
  ADD COLUMN IF NOT EXISTS last_performance_recomputed_at TIMESTAMPTZ;

ALTER TABLE IF EXISTS public.account_autoposter_state
  DROP CONSTRAINT IF EXISTS account_autoposter_state_strategy_mode_check;

ALTER TABLE IF EXISTS public.account_autoposter_state
  ADD CONSTRAINT account_autoposter_state_strategy_mode_check
  CHECK (
    recommended_strategy_mode IS NULL OR
    recommended_strategy_mode IN ('scale', 'clone_winners', 'test_market', 'reduce', 'suppress')
  );

CREATE TABLE IF NOT EXISTS public.autoposter_post_performance_facts (
  post_id TEXT PRIMARY KEY REFERENCES public.posts(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL,
  workspace_id TEXT,
  group_id TEXT,
  group_name TEXT,
  account_id TEXT,
  account_username TEXT,
  creator_key TEXT,

  content TEXT,
  published_at TIMESTAMPTZ,
  posting_hour INTEGER,
  platform TEXT NOT NULL DEFAULT 'threads',

  views_1h INTEGER NOT NULL DEFAULT 0,
  views_24h INTEGER NOT NULL DEFAULT 0,
  current_views INTEGER NOT NULL DEFAULT 0,
  replies_1h INTEGER NOT NULL DEFAULT 0,
  replies_24h INTEGER NOT NULL DEFAULT 0,
  current_replies INTEGER NOT NULL DEFAULT 0,
  likes_24h INTEGER NOT NULL DEFAULT 0,
  current_likes INTEGER NOT NULL DEFAULT 0,
  reposts_count INTEGER NOT NULL DEFAULT 0,
  quotes_count INTEGER NOT NULL DEFAULT 0,

  media_type TEXT,
  media_style TEXT,
  has_media BOOLEAN NOT NULL DEFAULT false,

  source_type TEXT,
  source_id TEXT,
  source_competitor_id TEXT,
  source_competitor_username TEXT,
  direct_copy_reason TEXT,
  microcopy_confidence NUMERIC,

  content_archetype TEXT,
  shape_id TEXT,
  hook_type TEXT,
  topic_label TEXT,
  format_type TEXT,
  emotional_frame TEXT,
  reply_mechanism TEXT,
  content_length_bucket TEXT,

  strategy_recommendation_id UUID REFERENCES public.autoposter_strategy_recommendations(id) ON DELETE SET NULL,
  strategy_bucket TEXT,
  prompt_version TEXT,
  template_id TEXT,
  model_provider TEXT,
  source_pattern_id TEXT,

  dna_fit_score NUMERIC,
  creator_fit_score NUMERIC,
  account_flavor_score NUMERIC,
  genericness_score NUMERIC,

  smart_link_clicks INTEGER NOT NULL DEFAULT 0,
  smart_link_conversions INTEGER NOT NULL DEFAULT 0,
  smart_link_revenue NUMERIC NOT NULL DEFAULT 0,
  profile_clicks_proxy INTEGER,
  profile_clicks_proxy_scope TEXT,

  metrics_quality TEXT NOT NULL DEFAULT 'views_only',
  metric_notes JSONB NOT NULL DEFAULT '{}'::jsonb,
  computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT autoposter_post_performance_facts_quality_check
  CHECK (metrics_quality IN (
    'complete',
    'views_only',
    'conversion_unavailable',
    'profile_click_proxy',
    'insufficient_metrics'
  ))
);

CREATE INDEX IF NOT EXISTS autoposter_perf_workspace_published_idx
  ON public.autoposter_post_performance_facts(workspace_id, published_at DESC);

CREATE INDEX IF NOT EXISTS autoposter_perf_group_views_idx
  ON public.autoposter_post_performance_facts(group_id, views_24h DESC, published_at DESC);

CREATE INDEX IF NOT EXISTS autoposter_perf_account_views_idx
  ON public.autoposter_post_performance_facts(account_id, views_24h DESC, published_at DESC);

CREATE INDEX IF NOT EXISTS autoposter_perf_pattern_idx
  ON public.autoposter_post_performance_facts(content_archetype, shape_id, source_type);

CREATE TABLE IF NOT EXISTS public.autoposter_winner_patterns (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id TEXT NOT NULL,
  group_id TEXT,
  account_id TEXT,
  creator_key TEXT,
  source_post_id TEXT NOT NULL REFERENCES public.posts(id) ON DELETE CASCADE,
  source_text TEXT NOT NULL,

  content_archetype TEXT,
  shape_id TEXT,
  topic_label TEXT,
  emotional_frame TEXT,
  content_length_bucket TEXT,
  reply_mechanism TEXT,
  media_style TEXT,
  source_type TEXT,
  posting_hour INTEGER,

  views_24h INTEGER NOT NULL DEFAULT 0,
  replies_1h INTEGER NOT NULL DEFAULT 0,
  link_clicks INTEGER NOT NULL DEFAULT 0,
  revenue NUMERIC NOT NULL DEFAULT 0,
  performance_basis TEXT NOT NULL,
  clone_prompt TEXT NOT NULL,
  confidence NUMERIC NOT NULL DEFAULT 0.5,
  expires_at TIMESTAMPTZ NOT NULL DEFAULT (now() + interval '14 days'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT autoposter_winner_patterns_basis_check
  CHECK (performance_basis IN (
    'views_above_100',
    'account_top_decile',
    'revenue_or_clicks',
    'early_velocity'
  )),
  CONSTRAINT autoposter_winner_patterns_confidence_check
  CHECK (confidence >= 0 AND confidence <= 1)
);

CREATE UNIQUE INDEX IF NOT EXISTS autoposter_winner_patterns_source_unique
  ON public.autoposter_winner_patterns(source_post_id, performance_basis);

CREATE INDEX IF NOT EXISTS autoposter_winner_patterns_active_idx
  ON public.autoposter_winner_patterns(workspace_id, group_id, confidence DESC, expires_at DESC);

ALTER TABLE IF EXISTS public.autoposter_post_performance_facts ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.autoposter_winner_patterns ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Workspace members can view autoposter performance facts"
  ON public.autoposter_post_performance_facts;
DROP POLICY IF EXISTS "Service role can manage autoposter performance facts"
  ON public.autoposter_post_performance_facts;
DROP POLICY IF EXISTS "Workspace members can view autoposter winner patterns"
  ON public.autoposter_winner_patterns;
DROP POLICY IF EXISTS "Service role can manage autoposter winner patterns"
  ON public.autoposter_winner_patterns;

DO $$
BEGIN
  IF to_regclass('public.autoposter_post_performance_facts') IS NOT NULL THEN
    EXECUTE $policy$
      CREATE POLICY "Workspace members can view autoposter performance facts"
      ON public.autoposter_post_performance_facts
      FOR SELECT
      TO authenticated
      USING (
        workspace_id IS NOT NULL AND EXISTS (
          SELECT 1
          FROM public.workspace_members wm
          WHERE wm.workspace_id = autoposter_post_performance_facts.workspace_id
            AND wm.user_id = (SELECT auth.uid())::text
        )
      )
    $policy$;
    EXECUTE $policy$
      CREATE POLICY "Service role can manage autoposter performance facts"
      ON public.autoposter_post_performance_facts
      FOR ALL
      TO service_role
      USING (true)
      WITH CHECK (true)
    $policy$;
  END IF;

  IF to_regclass('public.autoposter_winner_patterns') IS NOT NULL THEN
    EXECUTE $policy$
      CREATE POLICY "Workspace members can view autoposter winner patterns"
      ON public.autoposter_winner_patterns
      FOR SELECT
      TO authenticated
      USING (
        EXISTS (
          SELECT 1
          FROM public.workspace_members wm
          WHERE wm.workspace_id = autoposter_winner_patterns.workspace_id
            AND wm.user_id = (SELECT auth.uid())::text
        )
      )
    $policy$;
    EXECUTE $policy$
      CREATE POLICY "Service role can manage autoposter winner patterns"
      ON public.autoposter_winner_patterns
      FOR ALL
      TO service_role
      USING (true)
      WITH CHECK (true)
    $policy$;
  END IF;
END $$;

COMMIT;
