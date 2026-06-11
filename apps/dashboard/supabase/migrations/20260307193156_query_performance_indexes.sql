-- Backfilled from DB migration history
DO $$
DECLARE
  rec RECORD;
BEGIN
  FOR rec IN
    SELECT * FROM (VALUES
      ('idx_account_daily_summary_account_date', 'account_daily_summary', ARRAY['account_id', 'date'], 'account_id, date DESC', NULL),
      ('idx_threads_webhook_user_processed_created', 'threads_webhook_events', ARRAY['threads_user_id', 'processed', 'created_at'], 'threads_user_id, processed, created_at DESC', NULL),
      ('idx_user_preferences_opted_in', 'user_preferences', ARRAY['user_id', 'data_contribution_opted_in'], 'user_id', 'data_contribution_opted_in = true'),
      ('idx_ig_comments_ig_user_id', 'ig_comments', ARRAY['ig_user_id'], 'ig_user_id', NULL),
      ('idx_ig_mentions_ig_account_id', 'ig_mentions', ARRAY['ig_account_id'], 'ig_account_id', NULL),
      ('idx_listening_results_alert_checked', 'listening_results', ARRAY['alert_id', 'checked_at'], 'alert_id, checked_at DESC', NULL)
    ) AS v(index_name, table_name, column_names, index_expression, predicate)
  LOOP
    IF to_regclass(format('public.%I', rec.table_name)) IS NOT NULL
       AND NOT EXISTS (
         SELECT 1
         FROM unnest(rec.column_names) AS required_column(column_name)
         WHERE NOT EXISTS (
           SELECT 1
           FROM information_schema.columns
           WHERE table_schema = 'public'
             AND table_name = rec.table_name
             AND column_name = required_column.column_name
         )
       ) THEN
      EXECUTE format(
        'CREATE INDEX IF NOT EXISTS %I ON public.%I (%s)%s',
        rec.index_name,
        rec.table_name,
        rec.index_expression,
        CASE WHEN rec.predicate IS NULL THEN '' ELSE format(' WHERE %s', rec.predicate) END
      );
    END IF;
  END LOOP;
END $$;
