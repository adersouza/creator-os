-- Instagram Notify Me / manual mobile handoff state.

ALTER TABLE public.posts
  ADD COLUMN IF NOT EXISTS publish_mode TEXT NOT NULL DEFAULT 'auto',
  ADD COLUMN IF NOT EXISTS handoff_status TEXT,
  ADD COLUMN IF NOT EXISTS notification_sent_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS handoff_opened_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS caption_copied_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS media_downloaded_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS media_shared_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS manual_publish_confirmed_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS reminder_count INTEGER NOT NULL DEFAULT 0;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'posts_publish_mode_check'
      AND conrelid = 'public.posts'::regclass
  ) THEN
    ALTER TABLE public.posts
      ADD CONSTRAINT posts_publish_mode_check
      CHECK (publish_mode IN ('auto', 'notify'));
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'posts_handoff_status_check'
      AND conrelid = 'public.posts'::regclass
  ) THEN
    ALTER TABLE public.posts
      ADD CONSTRAINT posts_handoff_status_check
      CHECK (
        handoff_status IS NULL OR handoff_status IN (
          'notified',
          'opened',
          'caption_copied',
          'media_downloaded',
          'media_shared',
          'completed',
          'notification_unavailable'
        )
      );
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_posts_ig_notify_due
  ON public.posts (scheduled_for)
  WHERE platform = 'instagram'
    AND status = 'scheduled'
    AND publish_mode = 'notify';
