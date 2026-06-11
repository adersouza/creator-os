CREATE INDEX IF NOT EXISTS idx_post_replies_unread
  ON public.post_replies (post_id, created_at DESC)
  WHERE COALESCE(is_read, false) = false;
