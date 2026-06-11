-- Enable Realtime for inbox tables (comments, mentions, replies)
-- Allows frontend to receive live updates via Supabase Postgres Changes

DO $$
DECLARE
  target_table TEXT;
BEGIN
  FOREACH target_table IN ARRAY ARRAY['ig_comments', 'ig_mentions', 'post_replies', 'mentions']
  LOOP
    IF to_regclass(format('public.%I', target_table)) IS NOT NULL THEN
      IF NOT EXISTS (
        SELECT 1
        FROM pg_publication_tables
        WHERE pubname = 'supabase_realtime'
          AND schemaname = 'public'
          AND tablename = target_table
      ) THEN
        EXECUTE format('ALTER PUBLICATION supabase_realtime ADD TABLE public.%I', target_table);
      END IF;

      EXECUTE format('ALTER TABLE public.%I REPLICA IDENTITY FULL', target_table);
    END IF;
  END LOOP;
END $$;
