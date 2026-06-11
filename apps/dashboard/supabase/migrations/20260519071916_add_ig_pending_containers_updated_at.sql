-- Add updated_at for ig_pending_containers state transitions.
-- The publisher uses this timestamp to recover processing containers that were
-- claimed by a crashed or timed-out cron run.

ALTER TABLE public.ig_pending_containers
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

UPDATE public.ig_pending_containers
SET updated_at = COALESCE(last_checked_at, created_at, NOW())
WHERE updated_at IS NULL;

ALTER TABLE public.ig_pending_containers
  ALTER COLUMN updated_at SET DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_ig_pending_containers_processing_updated
  ON public.ig_pending_containers(updated_at ASC)
  WHERE status = 'processing';
