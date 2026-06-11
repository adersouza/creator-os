ALTER TABLE public.media
  ADD COLUMN IF NOT EXISTS account_id TEXT,
  ADD COLUMN IF NOT EXISTS account_platform TEXT;

ALTER TABLE public.media
  DROP CONSTRAINT IF EXISTS media_account_platform_check;

ALTER TABLE public.media
  ADD CONSTRAINT media_account_platform_check
  CHECK (account_platform IS NULL OR account_platform IN ('threads', 'instagram'));

CREATE INDEX IF NOT EXISTS idx_media_account_assignment
  ON public.media (user_id, account_platform, account_id, created_at DESC)
  WHERE account_id IS NOT NULL;
