CREATE INDEX IF NOT EXISTS idx_inbox_dm_unread
  ON public.inbox_dm_cache (user_id, last_message_at DESC)
  WHERE COALESCE(is_read, false) = false;
