-- Store Meta's IG Media `media_audio_type` field for video media such as Reels.
-- Values currently documented by Meta: MUSIC or ORIGINAL_SOUND.
ALTER TABLE IF EXISTS public.posts
  ADD COLUMN IF NOT EXISTS media_audio_type TEXT;

DO $$
BEGIN
  IF to_regclass('public.posts') IS NOT NULL
    AND NOT EXISTS (
      SELECT 1
      FROM pg_constraint
      WHERE conname = 'posts_media_audio_type_check'
        AND conrelid = 'public.posts'::regclass
    )
  THEN
    ALTER TABLE public.posts
      ADD CONSTRAINT posts_media_audio_type_check
      CHECK (
        media_audio_type IS NULL
        OR media_audio_type IN ('MUSIC', 'ORIGINAL_SOUND')
      );
  END IF;
END $$;
