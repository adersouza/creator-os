CREATE INDEX IF NOT EXISTS idx_ig_mentions_unread
  ON public.ig_mentions (user_id, mentioned_at DESC)
  WHERE COALESCE(is_read, false) = false;
