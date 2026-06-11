-- Multi-surface Campaign draft support v1.
-- Adds a first-class surface marker for Campaign Factory drafts while keeping
-- metadata.campaign_factory.content_surface as the compatibility copy.

ALTER TABLE IF EXISTS public.posts
  ADD COLUMN IF NOT EXISTS content_surface TEXT;

UPDATE public.posts
SET content_surface = CASE COALESCE(
    content_surface,
    NULLIF(metadata #>> '{campaign_factory,content_surface}', ''),
    NULLIF(metadata #>> '{campaign_factory,contentSurface}', ''),
    NULLIF(metadata #>> '{campaign_factory,handoff_manifest,content_surface}', ''),
    NULLIF(metadata #>> '{campaign_factory,handoff_manifest,contentSurface}', ''),
    NULLIF(metadata #>> '{campaign_factory,distribution_surface}', ''),
    CASE
      WHEN ig_media_type = 'REELS' THEN 'reel'
      WHEN ig_media_type = 'STORIES' THEN 'story'
      WHEN ig_media_type = 'CAROUSEL' OR ig_media_type = 'CAROUSEL_ALBUM' THEN 'feed_carousel'
      WHEN ig_media_type = 'IMAGE' THEN 'feed_single'
      ELSE NULL
    END
  )
  WHEN 'regular_reel' THEN 'reel'
  WHEN 'trial_reel' THEN 'reel'
  WHEN 'reels' THEN 'reel'
  WHEN 'stories' THEN 'story'
  WHEN 'story_cta' THEN 'story'
  WHEN 'image' THEN 'feed_single'
  WHEN 'feed_image' THEN 'feed_single'
  WHEN 'single_image' THEN 'feed_single'
  WHEN 'carousel' THEN 'feed_carousel'
  WHEN 'carousel_album' THEN 'feed_carousel'
  ELSE COALESCE(
    content_surface,
    NULLIF(metadata #>> '{campaign_factory,content_surface}', ''),
    NULLIF(metadata #>> '{campaign_factory,contentSurface}', ''),
    NULLIF(metadata #>> '{campaign_factory,handoff_manifest,content_surface}', ''),
    NULLIF(metadata #>> '{campaign_factory,handoff_manifest,contentSurface}', ''),
    CASE
      WHEN ig_media_type = 'REELS' THEN 'reel'
      WHEN ig_media_type = 'STORIES' THEN 'story'
      WHEN ig_media_type = 'CAROUSEL' OR ig_media_type = 'CAROUSEL_ALBUM' THEN 'feed_carousel'
      WHEN ig_media_type = 'IMAGE' THEN 'feed_single'
      ELSE NULL
    END
  )
END
WHERE content_surface IS NULL;

ALTER TABLE public.posts
  DROP CONSTRAINT IF EXISTS posts_content_surface_check;

ALTER TABLE public.posts
  ADD CONSTRAINT posts_content_surface_check
  CHECK (
    content_surface IS NULL
    OR content_surface IN ('reel', 'story', 'feed_single', 'feed_carousel')
  );

CREATE INDEX IF NOT EXISTS posts_content_surface_idx
  ON public.posts(user_id, platform, content_surface, status, scheduled_for)
  WHERE content_surface IS NOT NULL;
