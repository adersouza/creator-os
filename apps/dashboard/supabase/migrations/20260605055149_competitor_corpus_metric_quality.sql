BEGIN;

ALTER TABLE public.competitor_top_posts
  ADD COLUMN IF NOT EXISTS metric_source TEXT NOT NULL DEFAULT 'official_profile_posts',
  ADD COLUMN IF NOT EXISTS metric_quality TEXT NOT NULL DEFAULT 'stats_unavailable',
  ADD COLUMN IF NOT EXISTS metric_quality_reason TEXT,
  ADD COLUMN IF NOT EXISTS hook_type TEXT,
  ADD COLUMN IF NOT EXISTS topic_label TEXT,
  ADD COLUMN IF NOT EXISTS emotional_frame TEXT,
  ADD COLUMN IF NOT EXISTS cta_style TEXT,
  ADD COLUMN IF NOT EXISTS content_length_bucket TEXT,
  ADD COLUMN IF NOT EXISTS controversy_level TEXT,
  ADD COLUMN IF NOT EXISTS reply_mechanism TEXT,
  ADD COLUMN IF NOT EXISTS account_size_bucket TEXT,
  ADD COLUMN IF NOT EXISTS benchmark_classified_at TIMESTAMPTZ;

ALTER TABLE public.competitor_top_posts
  DROP CONSTRAINT IF EXISTS competitor_top_posts_metric_quality_check;

ALTER TABLE public.competitor_top_posts
  ADD CONSTRAINT competitor_top_posts_metric_quality_check
  CHECK (metric_quality IN (
    'stats_unavailable',
    'partial_engagement',
    'valid_engagement'
  ));

ALTER TABLE public.competitor_top_posts
  DROP CONSTRAINT IF EXISTS competitor_top_posts_metric_source_check;

ALTER TABLE public.competitor_top_posts
  ADD CONSTRAINT competitor_top_posts_metric_source_check
  CHECK (metric_source IN (
    'official_profile_posts',
    'apify_threads_post_scraper',
    'instagram_business_discovery',
    'manual_import',
    'unknown'
  ));

UPDATE public.competitor_top_posts ctp
SET
  metric_source = CASE
    WHEN COALESCE(ctp.platform, 'threads') = 'instagram' THEN 'instagram_business_discovery'
    WHEN ctp.enriched_at IS NOT NULL THEN 'apify_threads_post_scraper'
    ELSE 'official_profile_posts'
  END,
  metric_quality = CASE
    WHEN COALESCE(ctp.platform, 'threads') = 'instagram'
      AND (
        COALESCE(ctp.engagement_score, 0) > 0
        OR COALESCE(ctp.like_count, 0) > 0
        OR COALESCE(ctp.comments_count, 0) > 0
      )
      THEN 'valid_engagement'
    WHEN COALESCE(ctp.view_count, 0) > 0
      THEN 'valid_engagement'
    WHEN COALESCE(ctp.like_count, 0) > 0
      OR COALESCE(ctp.reply_count, 0) > 0
      OR COALESCE(ctp.repost_count, 0) > 0
      THEN 'partial_engagement'
    ELSE 'stats_unavailable'
  END,
  metric_quality_reason = CASE
    WHEN COALESCE(ctp.platform, 'threads') = 'instagram'
      AND (
        COALESCE(ctp.engagement_score, 0) > 0
        OR COALESCE(ctp.like_count, 0) > 0
        OR COALESCE(ctp.comments_count, 0) > 0
      )
      THEN 'instagram_business_discovery_metrics'
    WHEN COALESCE(ctp.view_count, 0) > 0
      THEN 'views_present'
    WHEN COALESCE(ctp.like_count, 0) > 0
      OR COALESCE(ctp.reply_count, 0) > 0
      OR COALESCE(ctp.repost_count, 0) > 0
      THEN 'engagement_present_without_views'
    ELSE 'official_threads_competitor_stats_unavailable'
  END
WHERE ctp.metric_quality = 'stats_unavailable'
  OR ctp.metric_quality_reason IS NULL;

UPDATE public.competitor_top_posts ctp
SET
  content_length_bucket = CASE
    WHEN length(COALESCE(ctp.content, '')) = 0 THEN 'empty'
    WHEN length(COALESCE(ctp.content, '')) <= 40 THEN 'micro'
    WHEN length(COALESCE(ctp.content, '')) <= 120 THEN 'short'
    WHEN length(COALESCE(ctp.content, '')) <= 280 THEN 'medium'
    ELSE 'long'
  END,
  hook_type = CASE
    WHEN COALESCE(ctp.content, '') ~ '\?$' THEN 'question'
    WHEN COALESCE(ctp.content, '') ~* '^(i|we|my|today|yesterday|last night)\b' THEN 'personal_statement'
    WHEN COALESCE(ctp.content, '') ~* '\b(unpopular opinion|hot take|be honest|controversial)\b' THEN 'hot_take'
    WHEN COALESCE(ctp.content, '') ~* '\b([0-9]+\.|1\.|top [0-9]+|reasons|ways)\b' THEN 'list'
    WHEN length(COALESCE(ctp.content, '')) <= 40 THEN 'short_statement'
    ELSE 'statement'
  END,
  emotional_frame = CASE
    WHEN COALESCE(ctp.content, '') ~* '\b(lonely|miss|sad|cry|hurt|anxious|scared)\b' THEN 'vulnerable'
    WHEN COALESCE(ctp.content, '') ~* '\b(happy|excited|love|cute|pretty|sweet)\b' THEN 'warm'
    WHEN COALESCE(ctp.content, '') ~* '\b(annoyed|mad|angry|hate|tired)\b' THEN 'frustrated'
    WHEN COALESCE(ctp.content, '') ~* '\b(would you|do you|am i|be honest|tell me)\b' THEN 'inviting'
    ELSE 'neutral'
  END,
  cta_style = CASE
    WHEN COALESCE(ctp.content, '') ~* '\b(reply|comment|tell me|drop|send|dm)\b' THEN 'explicit_reply'
    WHEN COALESCE(ctp.content, '') LIKE '%?%' THEN 'implicit_question'
    ELSE 'none'
  END,
  controversy_level = CASE
    WHEN COALESCE(ctp.content, '') ~* '\b(unpopular opinion|hot take|controversial|hate|red flag|toxic)\b' THEN 'high'
    WHEN COALESCE(ctp.content, '') ~* '\b(be honest|would you|should i|is it weird)\b' THEN 'medium'
    ELSE 'low'
  END,
  reply_mechanism = CASE
    WHEN COALESCE(ctp.content, '') ~* '\b(would you|do you|am i|should i|be honest)\b' THEN 'direct_prompt'
    WHEN COALESCE(ctp.content, '') ~* '\?$' THEN 'question'
    WHEN COALESCE(ctp.content, '') ~* '\b(confession|i admit|not gonna lie)\b' THEN 'confession'
    ELSE 'none'
  END,
  topic_label = COALESCE(NULLIF(ctp.topic_tag, ''), 'uncategorized'),
  account_size_bucket = CASE
    WHEN COALESCE(c.follower_count, 0) >= 100000 THEN '100k_plus'
    WHEN COALESCE(c.follower_count, 0) >= 50000 THEN '50k_100k'
    WHEN COALESCE(c.follower_count, 0) >= 10000 THEN '10k_50k'
    WHEN COALESCE(c.follower_count, 0) >= 1000 THEN '1k_10k'
    WHEN COALESCE(c.follower_count, 0) > 0 THEN 'under_1k'
    ELSE 'unknown'
  END,
  benchmark_classified_at = COALESCE(ctp.benchmark_classified_at, NOW())
FROM public.competitors c
WHERE ctp.competitor_id::text = c.id::text
  AND ctp.benchmark_classified_at IS NULL;

CREATE TABLE IF NOT EXISTS public.competitor_post_metric_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  competitor_post_id TEXT REFERENCES public.competitor_top_posts(id) ON DELETE CASCADE,
  competitor_id TEXT NOT NULL,
  user_id TEXT,
  threads_post_id TEXT,
  platform TEXT NOT NULL DEFAULT 'threads',
  metric_source TEXT NOT NULL DEFAULT 'official_profile_posts',
  metric_quality TEXT NOT NULL DEFAULT 'stats_unavailable',
  views INTEGER NOT NULL DEFAULT 0,
  likes INTEGER NOT NULL DEFAULT 0,
  replies INTEGER NOT NULL DEFAULT 0,
  reposts INTEGER NOT NULL DEFAULT 0,
  quotes INTEGER NOT NULL DEFAULT 0,
  engagement_score NUMERIC NOT NULL DEFAULT 0,
  follower_count_at_scrape INTEGER,
  scraped_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  raw_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT competitor_post_metric_snapshots_quality_check
    CHECK (metric_quality IN (
      'stats_unavailable',
      'partial_engagement',
      'valid_engagement'
    )),
  CONSTRAINT competitor_post_metric_snapshots_source_check
    CHECK (metric_source IN (
      'official_profile_posts',
      'apify_threads_post_scraper',
      'instagram_business_discovery',
      'manual_import',
      'unknown'
    ))
);

CREATE INDEX IF NOT EXISTS idx_competitor_posts_metric_quality
  ON public.competitor_top_posts(user_id, metric_quality, scraped_at DESC);

CREATE INDEX IF NOT EXISTS idx_competitor_posts_pattern_benchmark
  ON public.competitor_top_posts(user_id, hook_type, topic_label, scraped_at DESC);

CREATE INDEX IF NOT EXISTS idx_competitor_metric_snapshots_post_time
  ON public.competitor_post_metric_snapshots(competitor_post_id, scraped_at DESC);

CREATE INDEX IF NOT EXISTS idx_competitor_metric_snapshots_user_time
  ON public.competitor_post_metric_snapshots(user_id, scraped_at DESC);

ALTER TABLE public.competitor_post_metric_snapshots ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users can view own competitor metric snapshots"
  ON public.competitor_post_metric_snapshots;
CREATE POLICY "Users can view own competitor metric snapshots"
  ON public.competitor_post_metric_snapshots
  FOR SELECT
  TO authenticated
  USING ((SELECT auth.uid())::text = user_id);

DROP POLICY IF EXISTS "Users can insert own competitor metric snapshots"
  ON public.competitor_post_metric_snapshots;
CREATE POLICY "Users can insert own competitor metric snapshots"
  ON public.competitor_post_metric_snapshots
  FOR INSERT
  TO authenticated
  WITH CHECK ((SELECT auth.uid())::text = user_id);

DROP POLICY IF EXISTS "Users can update own competitor metric snapshots"
  ON public.competitor_post_metric_snapshots;
CREATE POLICY "Users can update own competitor metric snapshots"
  ON public.competitor_post_metric_snapshots
  FOR UPDATE
  TO authenticated
  USING ((SELECT auth.uid())::text = user_id)
  WITH CHECK ((SELECT auth.uid())::text = user_id);

INSERT INTO public.competitor_post_metric_snapshots (
  competitor_post_id,
  competitor_id,
  user_id,
  threads_post_id,
  platform,
  metric_source,
  metric_quality,
  views,
  likes,
  replies,
  reposts,
  engagement_score,
  follower_count_at_scrape,
  scraped_at,
  raw_metrics
)
SELECT
  ctp.id,
  ctp.competitor_id::text,
  ctp.user_id::text,
  ctp.threads_post_id,
  COALESCE(ctp.platform, 'threads'),
  ctp.metric_source,
  ctp.metric_quality,
  COALESCE(ctp.view_count, 0),
  COALESCE(ctp.like_count, 0),
  COALESCE(ctp.reply_count, 0),
  COALESCE(ctp.repost_count, 0),
  COALESCE(ctp.engagement_score, 0),
  c.follower_count,
  COALESCE(ctp.scraped_at, ctp.enriched_at, ctp.created_at, NOW()),
  jsonb_build_object(
    'backfilled_from', 'competitor_top_posts',
    'metric_quality_reason', ctp.metric_quality_reason
  )
FROM public.competitor_top_posts ctp
LEFT JOIN public.competitors c ON c.id::text = ctp.competitor_id::text
WHERE NOT EXISTS (
  SELECT 1
  FROM public.competitor_post_metric_snapshots s
  WHERE s.competitor_post_id = ctp.id
    AND s.scraped_at = COALESCE(ctp.scraped_at, ctp.enriched_at, ctp.created_at, NOW())
);

COMMIT;
