BEGIN;

ALTER TABLE public.competitor_top_posts
  ADD COLUMN IF NOT EXISTS last_metric_checked_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS format_type TEXT,
  ADD COLUMN IF NOT EXISTS media_style TEXT,
  ADD COLUMN IF NOT EXISTS posting_hour INTEGER;

ALTER TABLE public.competitor_top_posts
  DROP CONSTRAINT IF EXISTS competitor_top_posts_metric_quality_check;

ALTER TABLE public.competitor_top_posts
  ADD CONSTRAINT competitor_top_posts_metric_quality_check
  CHECK (metric_quality IN (
    'stats_unavailable',
    'partial_engagement',
    'valid_engagement',
    'scraper_estimated'
  ));

ALTER TABLE public.competitor_top_posts
  DROP CONSTRAINT IF EXISTS competitor_top_posts_posting_hour_check;

ALTER TABLE public.competitor_top_posts
  ADD CONSTRAINT competitor_top_posts_posting_hour_check
  CHECK (posting_hour IS NULL OR posting_hour BETWEEN 0 AND 23);

UPDATE public.competitor_top_posts ctp
SET
  metric_source = CASE
    WHEN COALESCE(ctp.platform, 'threads') = 'instagram' THEN 'instagram_business_discovery'
    WHEN ctp.enriched_at IS NOT NULL THEN 'apify_threads_post_scraper'
    ELSE COALESCE(NULLIF(ctp.metric_source, ''), 'official_profile_posts')
  END,
  metric_quality = CASE
    WHEN COALESCE(ctp.platform, 'threads') = 'instagram'
      AND (
        COALESCE(ctp.engagement_score, 0) > 0
        OR COALESCE(ctp.like_count, 0) > 0
        OR COALESCE(ctp.comments_count, 0) > 0
        OR COALESCE(ctp.view_count, 0) > 0
      )
      THEN 'valid_engagement'
    WHEN ctp.enriched_at IS NOT NULL
      AND (
        COALESCE(ctp.view_count, 0) > 0
        OR COALESCE(ctp.engagement_score, 0) > 0
        OR COALESCE(ctp.like_count, 0) > 0
        OR COALESCE(ctp.reply_count, 0) > 0
        OR COALESCE(ctp.repost_count, 0) > 0
      )
      THEN 'scraper_estimated'
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
        OR COALESCE(ctp.view_count, 0) > 0
      )
      THEN 'instagram_business_discovery_metrics'
    WHEN ctp.enriched_at IS NOT NULL
      AND COALESCE(ctp.view_count, 0) > 0
      THEN 'scraper_estimated_views_present'
    WHEN ctp.enriched_at IS NOT NULL
      AND (
        COALESCE(ctp.engagement_score, 0) > 0
        OR COALESCE(ctp.like_count, 0) > 0
        OR COALESCE(ctp.reply_count, 0) > 0
        OR COALESCE(ctp.repost_count, 0) > 0
      )
      THEN 'scraper_estimated_engagement_without_views'
    WHEN COALESCE(ctp.view_count, 0) > 0
      THEN 'views_present'
    WHEN COALESCE(ctp.like_count, 0) > 0
      OR COALESCE(ctp.reply_count, 0) > 0
      OR COALESCE(ctp.repost_count, 0) > 0
      THEN 'engagement_present_without_views'
    ELSE 'official_threads_competitor_stats_unavailable'
  END,
  last_metric_checked_at = COALESCE(
    ctp.last_metric_checked_at,
    ctp.enriched_at,
    ctp.scraped_at,
    ctp.created_at,
    NOW()
  );

UPDATE public.competitor_top_posts ctp
SET
  media_style = CASE
    WHEN upper(COALESCE(ctp.media_type, 'TEXT')) LIKE '%VIDEO%' THEN 'video'
    WHEN upper(COALESCE(ctp.media_type, 'TEXT')) LIKE '%CAROUSEL%' THEN 'carousel'
    WHEN upper(COALESCE(ctp.media_type, 'TEXT')) LIKE '%IMAGE%'
      OR upper(COALESCE(ctp.media_type, 'TEXT')) LIKE '%PHOTO%'
      THEN 'image'
    ELSE 'text_only'
  END,
  format_type = CASE
    WHEN upper(COALESCE(ctp.media_type, 'TEXT')) LIKE '%VIDEO%' THEN 'video_post'
    WHEN upper(COALESCE(ctp.media_type, 'TEXT')) LIKE '%CAROUSEL%'
      OR upper(COALESCE(ctp.media_type, 'TEXT')) LIKE '%IMAGE%'
      OR upper(COALESCE(ctp.media_type, 'TEXT')) LIKE '%PHOTO%'
      THEN 'media_post'
    WHEN COALESCE(ctp.hook_type, '') = 'list' THEN 'list_post'
    WHEN COALESCE(ctp.hook_type, '') = 'question' THEN 'question_post'
    WHEN COALESCE(ctp.hook_type, '') = 'hot_take' THEN 'hot_take_post'
    ELSE 'text_post'
  END,
  posting_hour = CASE
    WHEN COALESCE(ctp.published_at, ctp.scraped_at) IS NULL THEN NULL
    ELSE EXTRACT(HOUR FROM COALESCE(ctp.published_at, ctp.scraped_at))::integer
  END
WHERE ctp.format_type IS NULL
  OR ctp.media_style IS NULL
  OR ctp.posting_hour IS NULL;

ALTER TABLE public.competitor_post_metric_snapshots
  ADD COLUMN IF NOT EXISTS last_metric_checked_at TIMESTAMPTZ;

ALTER TABLE public.competitor_post_metric_snapshots
  DROP CONSTRAINT IF EXISTS competitor_post_metric_snapshots_quality_check;

ALTER TABLE public.competitor_post_metric_snapshots
  ADD CONSTRAINT competitor_post_metric_snapshots_quality_check
  CHECK (metric_quality IN (
    'stats_unavailable',
    'partial_engagement',
    'valid_engagement',
    'scraper_estimated'
  ));

UPDATE public.competitor_post_metric_snapshots s
SET
  metric_quality = ctp.metric_quality,
  metric_source = ctp.metric_source,
  last_metric_checked_at = COALESCE(
    s.last_metric_checked_at,
    ctp.last_metric_checked_at,
    s.scraped_at,
    s.created_at,
    NOW()
  ),
  raw_metrics = COALESCE(s.raw_metrics, '{}'::jsonb) || jsonb_build_object(
    'metric_quality_reason', ctp.metric_quality_reason
  )
FROM public.competitor_top_posts ctp
WHERE s.competitor_post_id = ctp.id;

CREATE INDEX IF NOT EXISTS idx_competitor_posts_pattern_format
  ON public.competitor_top_posts(user_id, format_type, media_style, scraped_at DESC);

CREATE INDEX IF NOT EXISTS idx_competitor_posts_pattern_hour
  ON public.competitor_top_posts(user_id, posting_hour, scraped_at DESC);

COMMIT;
