CREATE INDEX IF NOT EXISTS idx_mentions_unread
  ON public.mentions (user_id, created_at DESC)
  WHERE COALESCE(is_read, false) = false;
