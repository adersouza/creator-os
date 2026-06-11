-- Autoposter Audit Fixes (2026-03-22)
-- Fixes: H10 (competitor dedup), M7 (cancel status normalization), M12 (velocity_score column)

-- ============================================================================
-- H10: Deduplicate competitors table
-- 123 rows = 52 unique usernames. Same competitor tracked 3-5x wastes API quota.
-- Keep the row with the most recent last_synced_at for each (user_id, username, platform).
-- ============================================================================

DELETE FROM public.competitors
WHERE id NOT IN (
  SELECT DISTINCT ON (user_id, username, platform) id
  FROM public.competitors
  ORDER BY user_id, username, platform, last_synced_at DESC NULLS LAST
);

-- Prevent future duplicates
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'competitors_user_username_platform_unique'
  ) THEN
    ALTER TABLE public.competitors
      ADD CONSTRAINT competitors_user_username_platform_unique
      UNIQUE (user_id, username, platform);
  END IF;
END $$;

-- ============================================================================
-- M7: Normalize cancelled/canceled spelling
-- 475 rows with 'cancelled', 817 with 'canceled'. Standardize to 'cancelled'.
-- ============================================================================

UPDATE public.auto_post_queue SET status = 'cancelled' WHERE status = 'canceled';

-- Update status CHECK constraint to remove 'canceled' (keep only 'cancelled')
ALTER TABLE public.auto_post_queue
  DROP CONSTRAINT IF EXISTS auto_post_queue_status_check;

ALTER TABLE public.auto_post_queue
  ADD CONSTRAINT auto_post_queue_status_check
  CHECK (status IN ('pending', 'processing', 'posted', 'published', 'failed',
                    'dead_letter', 'cancelled', 'rejected', 'queued', 'scheduled'));

-- ============================================================================
-- M12: Add velocity_score column to auto_post_queue
-- Prevents content-ab-testing from overwriting predicted_viral_score (used by recycler).
-- ============================================================================

ALTER TABLE public.auto_post_queue
  ADD COLUMN IF NOT EXISTS velocity_score REAL;
