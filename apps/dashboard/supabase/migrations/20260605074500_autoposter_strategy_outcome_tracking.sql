BEGIN;

ALTER TABLE public.autoposter_strategy_recommendations
  ADD COLUMN IF NOT EXISTS outcome_sample_count INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS below_baseline_count INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_outcome_checked_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS downgraded_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS expired_early_at TIMESTAMPTZ;

ALTER TABLE public.auto_post_queue
  ADD COLUMN IF NOT EXISTS strategy_recommendation_id UUID
    REFERENCES public.autoposter_strategy_recommendations(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS strategy_bucket TEXT NOT NULL DEFAULT 'none';

ALTER TABLE public.posts
  ADD COLUMN IF NOT EXISTS strategy_recommendation_id UUID
    REFERENCES public.autoposter_strategy_recommendations(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS strategy_bucket TEXT NOT NULL DEFAULT 'none';

ALTER TABLE public.auto_post_queue
  DROP CONSTRAINT IF EXISTS auto_post_queue_strategy_bucket_check;
ALTER TABLE public.auto_post_queue
  ADD CONSTRAINT auto_post_queue_strategy_bucket_check
  CHECK (strategy_bucket IN ('proven', 'exploration', 'weird', 'none'));

ALTER TABLE public.posts
  DROP CONSTRAINT IF EXISTS posts_strategy_bucket_check;
ALTER TABLE public.posts
  ADD CONSTRAINT posts_strategy_bucket_check
  CHECK (strategy_bucket IN ('proven', 'exploration', 'weird', 'none'));

UPDATE public.posts p
SET
  strategy_recommendation_id = COALESCE(p.strategy_recommendation_id, q.strategy_recommendation_id),
  strategy_bucket = COALESCE(NULLIF(p.strategy_bucket, 'none'), q.strategy_bucket, 'none')
FROM public.auto_post_queue q
WHERE q.id::text = COALESCE(p.auto_post_queue_id, p.metadata->>'autoPostQueueId')
  AND (
    p.strategy_recommendation_id IS NULL
    OR p.strategy_bucket = 'none'
  );

CREATE OR REPLACE FUNCTION public.copy_autoposter_strategy_outcome_fields()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
  v_queue_id TEXT;
  v_strategy_id UUID;
  v_strategy_bucket TEXT;
BEGIN
  v_queue_id := COALESCE(NEW.auto_post_queue_id, NEW.metadata->>'autoPostQueueId');

  IF v_queue_id IS NULL THEN
    NEW.strategy_bucket := COALESCE(NEW.strategy_bucket, 'none');
    RETURN NEW;
  END IF;

  SELECT strategy_recommendation_id, strategy_bucket
    INTO v_strategy_id, v_strategy_bucket
    FROM public.auto_post_queue
    WHERE id::text = v_queue_id
    LIMIT 1;

  NEW.strategy_recommendation_id := COALESCE(
    NEW.strategy_recommendation_id,
    v_strategy_id
  );
  NEW.strategy_bucket := COALESCE(
    NULLIF(NEW.strategy_bucket, 'none'),
    v_strategy_bucket,
    'none'
  );

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_posts_copy_autoposter_strategy_outcome_fields
  ON public.posts;
CREATE TRIGGER trg_posts_copy_autoposter_strategy_outcome_fields
  BEFORE INSERT OR UPDATE OF auto_post_queue_id, metadata, strategy_recommendation_id, strategy_bucket
  ON public.posts
  FOR EACH ROW
  EXECUTE FUNCTION public.copy_autoposter_strategy_outcome_fields();

CREATE INDEX IF NOT EXISTS idx_auto_post_queue_strategy_outcome
  ON public.auto_post_queue(strategy_recommendation_id, strategy_bucket, posted_at DESC);

CREATE INDEX IF NOT EXISTS idx_posts_strategy_outcome
  ON public.posts(strategy_recommendation_id, strategy_bucket, published_at DESC)
  WHERE status = 'published';

COMMIT;
