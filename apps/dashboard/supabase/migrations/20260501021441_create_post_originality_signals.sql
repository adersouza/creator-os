-- Derived originality/provenance fingerprints for published posts.
-- Text/recycle scoring can run directly from posts, but media-level originality
-- needs a durable capture layer so analytics does not repeatedly fetch media.

CREATE TABLE IF NOT EXISTS public.post_originality_signals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  account_id TEXT REFERENCES accounts(id) ON DELETE CASCADE,
  instagram_account_id UUID REFERENCES instagram_accounts(id) ON DELETE CASCADE,
  platform TEXT NOT NULL CHECK (platform IN ('threads', 'instagram')),
  text_hash TEXT,
  media_url_hashes TEXT[] NOT NULL DEFAULT '{}'::text[],
  perceptual_hashes TEXT[] NOT NULL DEFAULT '{}'::text[],
  watermark_applied BOOLEAN NOT NULL DEFAULT false,
  provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
  captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(post_id)
);

CREATE INDEX IF NOT EXISTS post_originality_user_recent_idx
  ON public.post_originality_signals (user_id, captured_at DESC);

CREATE INDEX IF NOT EXISTS post_originality_media_hash_idx
  ON public.post_originality_signals USING GIN (media_url_hashes);

CREATE INDEX IF NOT EXISTS post_originality_phash_idx
  ON public.post_originality_signals USING GIN (perceptual_hashes);

ALTER TABLE public.post_originality_signals ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users view own originality signals"
  ON public.post_originality_signals FOR SELECT
  USING ((SELECT auth.uid())::text = user_id);

CREATE POLICY "Service role manages originality signals"
  ON public.post_originality_signals FOR ALL
  USING ((auth.jwt()->>'role') = 'service_role')
  WITH CHECK ((auth.jwt()->>'role') = 'service_role');
