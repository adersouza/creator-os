-- Tenant-scope competitor_top_posts uniqueness.
--
-- The previous unique index on threads_post_id made the same public Threads post
-- globally owned by whichever tenant synced it first. Keep as much data as
-- possible by only deduping rows that collide within the same tenant after
-- backfilling user_id from competitors.

BEGIN;

ALTER TABLE public.competitor_top_posts
  ADD COLUMN IF NOT EXISTS user_id TEXT REFERENCES public.profiles(id) ON DELETE CASCADE;

DO $$
DECLARE
  user_id_type TEXT;
BEGIN
  SELECT data_type INTO user_id_type
  FROM information_schema.columns
  WHERE table_schema = 'public'
    AND table_name = 'competitor_top_posts'
    AND column_name = 'user_id';

  IF user_id_type = 'uuid' THEN
    UPDATE public.competitor_top_posts ctp
    SET user_id = c.user_id::uuid
    FROM public.competitors c
    WHERE ctp.competitor_id::text = c.id
      AND ctp.user_id IS NULL
      AND c.user_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';
  ELSIF user_id_type IS NOT NULL THEN
    UPDATE public.competitor_top_posts ctp
    SET user_id = c.user_id
    FROM public.competitors c
    WHERE ctp.competitor_id::text = c.id
      AND ctp.user_id IS NULL;
  END IF;
END $$;

DELETE FROM public.competitor_top_posts a
USING public.competitor_top_posts b
WHERE a.user_id IS NOT DISTINCT FROM b.user_id
  AND a.threads_post_id = b.threads_post_id
  AND a.threads_post_id IS NOT NULL
  AND a.id <> b.id
  AND (
    COALESCE(a.scraped_at, a.created_at) < COALESCE(b.scraped_at, b.created_at)
    OR (
      COALESCE(a.scraped_at, a.created_at) = COALESCE(b.scraped_at, b.created_at)
      AND a.id < b.id
    )
  );

ALTER TABLE public.competitor_top_posts
  DROP CONSTRAINT IF EXISTS competitor_top_posts_threads_post_id_key;

DROP INDEX IF EXISTS public.idx_competitor_top_posts_threads_post_id;

CREATE UNIQUE INDEX IF NOT EXISTS idx_competitor_top_posts_user_threads_post_id
  ON public.competitor_top_posts(user_id, threads_post_id);

CREATE INDEX IF NOT EXISTS idx_competitor_top_posts_user_id
  ON public.competitor_top_posts(user_id);

-- Trend-generated queue items are intentionally routed to review unless they
-- have passed the full autoposter gates.
ALTER TABLE public.auto_post_queue
  DROP CONSTRAINT IF EXISTS auto_post_queue_status_check;

ALTER TABLE public.auto_post_queue
  ADD CONSTRAINT auto_post_queue_status_check
  CHECK (status IN (
    'pending',
    'processing',
    'publishing',
    'posted',
    'published',
    'failed',
    'dead_letter',
    'cancelled',
    'canceled',
    'rejected',
    'queued',
    'scheduled',
    'needs_review',
    'retry_pending'
  ));

CREATE INDEX IF NOT EXISTS idx_auto_post_queue_needs_review
  ON public.auto_post_queue(workspace_id, group_id, created_at DESC)
  WHERE status = 'needs_review';

COMMIT;
