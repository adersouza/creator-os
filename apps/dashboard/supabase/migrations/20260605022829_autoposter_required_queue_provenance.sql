-- Required queue provenance for autoposter publish safety.
-- Provenance is enforced in application preflight and surfaced by doctor checks.

ALTER TABLE IF EXISTS public.auto_post_queue
  ADD COLUMN IF NOT EXISTS content_fingerprint TEXT,
  ADD COLUMN IF NOT EXISTS generation_id TEXT,
  ADD COLUMN IF NOT EXISTS source_id TEXT,
  ADD COLUMN IF NOT EXISTS provenance_status TEXT NOT NULL DEFAULT 'unchecked',
  ADD COLUMN IF NOT EXISTS provenance_error TEXT;

ALTER TABLE IF EXISTS public.posts
  ADD COLUMN IF NOT EXISTS content_fingerprint TEXT,
  ADD COLUMN IF NOT EXISTS generation_id TEXT,
  ADD COLUMN IF NOT EXISTS source_id TEXT,
  ADD COLUMN IF NOT EXISTS provenance_status TEXT,
  ADD COLUMN IF NOT EXISTS provenance_error TEXT;

CREATE INDEX IF NOT EXISTS idx_auto_post_queue_provenance_status
  ON public.auto_post_queue(workspace_id, provenance_status, created_at DESC)
  WHERE status IN ('pending', 'queued', 'publishing', 'needs_review', 'published');

CREATE INDEX IF NOT EXISTS idx_auto_post_queue_missing_provenance
  ON public.auto_post_queue(workspace_id, status, created_at DESC)
  WHERE source_type IS DISTINCT FROM 'manual'
    AND status IN ('pending', 'queued', 'publishing')
    AND (
      provenance_status IN ('missing', 'unchecked')
      OR provenance_error IS NOT NULL
      OR source_type IS NULL
      OR (content_fingerprint IS NULL AND publish_fingerprint IS NULL)
    );

CREATE INDEX IF NOT EXISTS idx_posts_provenance_status
  ON public.posts(provenance_status, published_at DESC)
  WHERE source IN ('auto-poster', 'auto-poster-reconciled');

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
      'duplicate_fingerprint_needs_review',
      'provenance_missing_blocked',
      'provenance_missing_needs_review',
      'provenance_manual_allowed'
    )
  );

COMMENT ON COLUMN public.auto_post_queue.content_fingerprint IS
  'Stable content lineage fingerprint from the generation/provenance layer when available.';
COMMENT ON COLUMN public.auto_post_queue.generation_id IS
  'Generation run or content pipeline identifier for AI/system-created queue rows.';
COMMENT ON COLUMN public.auto_post_queue.source_id IS
  'Canonical upstream source identifier for generated, competitor, recycled, or system queue rows.';
COMMENT ON COLUMN public.auto_post_queue.provenance_status IS
  'unchecked, pass, manual_allowed, missing, or needs_review provenance status.';
COMMENT ON COLUMN public.auto_post_queue.provenance_error IS
  'Machine-readable reason when required provenance is missing.';
