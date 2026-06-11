-- Publish fingerprint duplicate guard for autoposter.
-- Stores deterministic normalized text/media hashes on queue rows and posts so
-- queue-time, publish-time, and doctor retroactive checks use the same contract.

ALTER TABLE IF EXISTS public.auto_post_queue
  ADD COLUMN IF NOT EXISTS platform TEXT NOT NULL DEFAULT 'threads',
  ADD COLUMN IF NOT EXISTS normalized_text_hash TEXT,
  ADD COLUMN IF NOT EXISTS media_fingerprint TEXT,
  ADD COLUMN IF NOT EXISTS publish_fingerprint TEXT,
  ADD COLUMN IF NOT EXISTS duplicate_window_hours INTEGER NOT NULL DEFAULT 72,
  ADD COLUMN IF NOT EXISTS duplicate_of_queue_item_id TEXT;

ALTER TABLE IF EXISTS public.posts
  ADD COLUMN IF NOT EXISTS normalized_text_hash TEXT,
  ADD COLUMN IF NOT EXISTS media_fingerprint TEXT,
  ADD COLUMN IF NOT EXISTS publish_fingerprint TEXT,
  ADD COLUMN IF NOT EXISTS duplicate_window_hours INTEGER;

CREATE INDEX IF NOT EXISTS idx_auto_post_queue_publish_fingerprint_recent
  ON public.auto_post_queue(workspace_id, account_id, platform, normalized_text_hash, media_fingerprint, created_at DESC)
  WHERE normalized_text_hash IS NOT NULL
    AND status IN ('pending', 'queued', 'publishing', 'published', 'needs_review');

CREATE INDEX IF NOT EXISTS idx_auto_post_queue_publish_fingerprint
  ON public.auto_post_queue(publish_fingerprint)
  WHERE publish_fingerprint IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_posts_publish_fingerprint_recent
  ON public.posts(account_id, platform, normalized_text_hash, media_fingerprint, published_at DESC)
  WHERE normalized_text_hash IS NOT NULL
    AND status = 'published';

CREATE INDEX IF NOT EXISTS idx_posts_publish_fingerprint
  ON public.posts(publish_fingerprint)
  WHERE publish_fingerprint IS NOT NULL;

ALTER TABLE IF EXISTS public.publish_attempts
  DROP CONSTRAINT IF EXISTS publish_attempts_result_check;

ALTER TABLE IF EXISTS public.publish_attempts
  ADD CONSTRAINT publish_attempts_result_check CHECK (
    result IN (
      'started',
      'claim_failed',
      'requeued',
      'dead_letter',
      'published',
      'needs_reconciliation',
      'reconciled',
      'reconcile_failed',
      'failed',
      'error',
      'duplicate_fingerprint_blocked',
      'duplicate_fingerprint_needs_review'
    )
  );

COMMENT ON COLUMN public.auto_post_queue.normalized_text_hash IS
  'SHA-256 of normalized publish text used for duplicate-content prevention.';
COMMENT ON COLUMN public.auto_post_queue.media_fingerprint IS
  'SHA-256 of sorted normalized media URLs, or no_media for text-only posts.';
COMMENT ON COLUMN public.auto_post_queue.publish_fingerprint IS
  'SHA-256 of workspace/account/platform/text hash/media fingerprint when account is known; otherwise queue-scoped candidate fingerprint.';
COMMENT ON COLUMN public.auto_post_queue.duplicate_window_hours IS
  'Lookback window used by duplicate publish checks. Defaults to 72 hours.';
COMMENT ON COLUMN public.auto_post_queue.duplicate_of_queue_item_id IS
  'Queue row that caused this candidate to be routed to review or blocked as a duplicate.';
