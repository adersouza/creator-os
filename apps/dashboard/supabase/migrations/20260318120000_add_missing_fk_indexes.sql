-- Add covering indexes for 11 unindexed foreign keys
-- Supabase linter: unindexed_foreign_keys (0001)
-- FK constraint checks need the FK column as the LEADING index column.
-- Existing composite indexes (user_id, fk_col) don't satisfy this.

DO $$
DECLARE
  rec RECORD;
BEGIN
  FOR rec IN
    SELECT * FROM (VALUES
      ('idx_agent_notes_account_group_id', 'agent_notes', 'account_group_id'),
      ('idx_auto_reply_queue_group_id', 'auto_reply_queue', 'group_id'),
      ('idx_creator_events_account_id', 'creator_events', 'account_id'),
      ('idx_media_workspace_id', 'media', 'workspace_id'),
      ('idx_posts_draft_folder_id', 'posts', 'draft_folder_id'),
      ('idx_posts_rejected_by', 'posts', 'rejected_by'),
      ('idx_quick_wins_account_id', 'quick_wins', 'account_id'),
      ('idx_recommendation_dismissals_account_id', 'recommendation_dismissals', 'account_id'),
      ('idx_revenue_snapshots_account_group_id', 'revenue_snapshots', 'account_group_id'),
      ('idx_saved_competitor_posts_workspace_id', 'saved_competitor_posts', 'workspace_id'),
      ('idx_style_bibles_account_id', 'style_bibles', 'account_id')
    ) AS v(index_name, table_name, column_name)
  LOOP
    IF to_regclass(format('public.%I', rec.table_name)) IS NOT NULL THEN
      BEGIN
        EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON public.%I (%I)', rec.index_name, rec.table_name, rec.column_name);
      EXCEPTION
        WHEN undefined_column THEN NULL;
      END;
    END IF;
  END LOOP;
END $$;
