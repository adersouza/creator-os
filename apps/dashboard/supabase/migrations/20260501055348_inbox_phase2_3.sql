CREATE UNIQUE INDEX IF NOT EXISTS idx_inbox_ai_suggestions_one_pending
  ON public.inbox_ai_suggestions(user_id, conversation_key)
  WHERE status = 'pending';
