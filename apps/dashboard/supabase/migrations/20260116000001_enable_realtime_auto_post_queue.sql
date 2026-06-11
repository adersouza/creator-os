-- Migration: Enable real-time for auto_post_queue table
-- This allows the UI to receive instant updates when:
-- 1. AI generates new posts
-- 2. Posts are published by the cron worker
-- 3. Posts are removed from the queue

-- Enable replica identity for the table (required for UPDATE/DELETE events)
ALTER TABLE public.auto_post_queue REPLICA IDENTITY FULL;

-- Add the table to the supabase_realtime publication
-- Note: This may already exist, so we use IF NOT EXISTS pattern
DO $$
BEGIN
  -- Check if table is already in the publication
  IF NOT EXISTS (
    SELECT 1 FROM pg_publication_tables
    WHERE pubname = 'supabase_realtime'
    AND tablename = 'auto_post_queue'
  ) THEN
    ALTER PUBLICATION supabase_realtime ADD TABLE public.auto_post_queue;
  END IF;
END $$;

-- Also enable for auto_post_state and auto_post_activity if not already
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_publication_tables
    WHERE pubname = 'supabase_realtime'
    AND tablename = 'auto_post_state'
  ) THEN
    ALTER PUBLICATION supabase_realtime ADD TABLE public.auto_post_state;
    ALTER TABLE public.auto_post_state REPLICA IDENTITY FULL;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_publication_tables
    WHERE pubname = 'supabase_realtime'
    AND tablename = 'auto_post_activity'
  ) THEN
    ALTER PUBLICATION supabase_realtime ADD TABLE public.auto_post_activity;
    ALTER TABLE public.auto_post_activity REPLICA IDENTITY FULL;
  END IF;
END $$;
