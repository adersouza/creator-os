-- Enrich ig_comments for local-first CommentPanel
-- Adds columns the CommentPanel Comment interface expects

ALTER TABLE ig_comments ADD COLUMN IF NOT EXISTS like_count INTEGER DEFAULT 0;
ALTER TABLE ig_comments ADD COLUMN IF NOT EXISTS parent_comment_id TEXT;
ALTER TABLE ig_comments ADD COLUMN IF NOT EXISTS is_own_reply BOOLEAN DEFAULT false;
ALTER TABLE ig_comments ADD COLUMN IF NOT EXISTS account_id UUID;

-- RLS policy for frontend reads
-- ig_comments has RLS enabled since 20260208 but no SELECT policy was created,
-- so frontend queries return empty. Fix that now.
CREATE POLICY "Users can read own post comments"
  ON ig_comments FOR SELECT
  USING (
    EXISTS (
      SELECT 1 FROM posts p
      WHERE p.id = ig_comments.post_id
      AND p.user_id = auth.uid()::text
    )
  );
