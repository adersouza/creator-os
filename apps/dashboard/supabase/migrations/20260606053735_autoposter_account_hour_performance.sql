CREATE TABLE IF NOT EXISTS public.autoposter_account_hour_performance (
  workspace_id TEXT NOT NULL,
  group_id TEXT,
  account_id TEXT NOT NULL,
  platform TEXT NOT NULL DEFAULT 'threads',
  hour INTEGER NOT NULL,
  posts_count INTEGER NOT NULL DEFAULT 0,
  effective_sample_size NUMERIC NOT NULL DEFAULT 0,
  avg_views_24h NUMERIC NOT NULL DEFAULT 0,
  median_views_24h NUMERIC NOT NULL DEFAULT 0,
  above_100_rate NUMERIC NOT NULL DEFAULT 0,
  avg_replies_24h NUMERIC NOT NULL DEFAULT 0,
  profile_clicks_proxy NUMERIC NOT NULL DEFAULT 0,
  weighted_score NUMERIC NOT NULL DEFAULT 0,
  confidence NUMERIC NOT NULL DEFAULT 0,
  fallback_source TEXT NOT NULL DEFAULT 'account_sparse',
  last_seen_at TIMESTAMPTZ,
  computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT autoposter_account_hour_performance_platform_check
    CHECK (platform IN ('threads')),
  CONSTRAINT autoposter_account_hour_performance_hour_check
    CHECK (hour BETWEEN 0 AND 23),
  CONSTRAINT autoposter_account_hour_performance_confidence_check
    CHECK (confidence >= 0 AND confidence <= 1),
  CONSTRAINT autoposter_account_hour_performance_above_100_check
    CHECK (above_100_rate >= 0 AND above_100_rate <= 1),
  CONSTRAINT autoposter_account_hour_performance_source_check
    CHECK (fallback_source IN ('account_learned', 'account_sparse')),

  PRIMARY KEY (workspace_id, account_id, platform, hour)
);

CREATE INDEX IF NOT EXISTS autoposter_account_hour_perf_group_idx
  ON public.autoposter_account_hour_performance(workspace_id, group_id, account_id, weighted_score DESC);

CREATE INDEX IF NOT EXISTS autoposter_account_hour_perf_confidence_idx
  ON public.autoposter_account_hour_performance(workspace_id, account_id, confidence DESC, weighted_score DESC);

CREATE INDEX IF NOT EXISTS autoposter_perf_facts_threads_hour_idx
  ON public.autoposter_post_performance_facts(account_id, posting_hour, published_at DESC)
  WHERE platform = 'threads' AND account_id IS NOT NULL AND posting_hour IS NOT NULL;

ALTER TABLE public.autoposter_account_hour_performance ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'autoposter_account_hour_performance'
      AND policyname = 'service role manages autoposter account hour performance'
  ) THEN
    CREATE POLICY "service role manages autoposter account hour performance"
      ON public.autoposter_account_hour_performance
      FOR ALL
      TO service_role
      USING (true)
      WITH CHECK (true);
  END IF;
END $$;
