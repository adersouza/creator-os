-- Add spoofing observability columns to posts table
-- Tracks whether media was spoofed and the techniques/PDQ distances achieved.
-- Data-only, no frontend UI — used for reach monitoring and pipeline health.

ALTER TABLE posts
  ADD COLUMN IF NOT EXISTS spoofed BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS spoof_techniques JSONB DEFAULT NULL;

-- Index for filtering spoofed vs unspoofed in analytics queries
CREATE INDEX IF NOT EXISTS idx_posts_spoofed ON posts (spoofed) WHERE spoofed = TRUE;

COMMENT ON COLUMN posts.spoofed IS 'Whether media was processed by the spoofing pipeline before publish';
COMMENT ON COLUMN posts.spoof_techniques IS 'Spoofing metadata: images/videos processed, PDQ distances, pass/fail';
