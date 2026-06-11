CREATE INDEX IF NOT EXISTS idx_ig_comments_unread
  ON public.ig_comments (post_id, created_at DESC)
  WHERE COALESCE(is_read, false) = false;
