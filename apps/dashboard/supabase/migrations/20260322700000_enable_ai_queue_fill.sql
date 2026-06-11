-- Enable AI queue fill for all active workspaces
-- The column defaults to FALSE (migration 20260218150100), which means
-- the decoupled queue-fill via QStash never dispatches. Without this,
-- the autoposter runs the publish cron but never generates new content.

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'auto_post_config'
      AND column_name = 'is_enabled'
  ) THEN
    UPDATE public.auto_post_config
    SET enable_ai_queue_fill = true
    WHERE is_enabled = true;
  ELSIF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'auto_post_config'
      AND column_name = 'enabled'
  ) THEN
    UPDATE public.auto_post_config
    SET enable_ai_queue_fill = true
    WHERE enabled = true;
  END IF;
END $$;
