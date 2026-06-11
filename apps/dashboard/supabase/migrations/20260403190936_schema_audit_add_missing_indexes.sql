-- Reconstructed from schema_migrations on prod (remote-only).
-- version: 20260403190936
-- applied-by: schema_audit_add_missing_indexes migration row


-- =============================================================================
-- SCHEMA AUDIT: Add 22 missing indexes
-- Prioritized by query frequency (cron hot paths first)
-- =============================================================================

DO $$
DECLARE
  idx record;
BEGIN
  FOR idx IN
    SELECT *
    FROM (VALUES
      ('idx_posts_approval_status', 'posts', 'approval_status'),
      ('idx_accounts_is_active', 'accounts', 'is_active'),
      ('idx_ig_comments_account_id', 'ig_comments', 'account_id'),
      ('idx_ig_pending_containers_account_id', 'ig_pending_containers', 'account_id'),
      ('idx_ig_pending_containers_status', 'ig_pending_containers', 'status'),
      ('idx_listening_results_workspace_id', 'listening_results', 'workspace_id'),
      ('idx_workspace_activity_user_id', 'workspace_activity', 'user_id'),
      ('idx_crisis_events_workspace_id', 'crisis_events', 'workspace_id'),
      ('idx_crisis_events_post_id', 'crisis_events', 'post_id'),
      ('idx_account_health_snapshots_workspace_id', 'account_health_snapshots', 'workspace_id'),
      ('idx_account_health_snapshots_platform', 'account_health_snapshots', 'platform'),
      ('idx_auto_cross_replies_workspace_id', 'auto_cross_replies', 'workspace_id'),
      ('idx_auto_self_replies_account_id', 'auto_self_replies', 'account_id'),
      ('idx_auto_self_replies_workspace_id', 'auto_self_replies', 'workspace_id'),
      ('idx_auto_post_config_is_enabled', 'auto_post_config', 'is_enabled'),
      ('idx_inbox_dm_cache_account_id', 'inbox_dm_cache', 'account_id'),
      ('idx_ig_collab_invites_account_id', 'ig_collab_invites', 'account_id'),
      ('idx_competitor_top_posts_platform', 'competitor_top_posts', 'platform'),
      ('idx_competitor_top_posts_published_at', 'competitor_top_posts', 'published_at'),
      ('idx_influencer_collabs_workspace_id', 'influencer_collabs', 'workspace_id'),
      ('idx_audit_logs_user_id', 'audit_logs', 'user_id'),
      ('idx_favorites_post_id', 'favorites', 'post_id')
    ) AS v(index_name, table_name, column_name)
  LOOP
    IF to_regclass(format('public.%I', idx.table_name)) IS NOT NULL
       AND EXISTS (
         SELECT 1
         FROM information_schema.columns c
         WHERE c.table_schema = 'public'
           AND c.table_name = idx.table_name
           AND c.column_name = idx.column_name
       ) THEN
      EXECUTE format(
        'CREATE INDEX IF NOT EXISTS %I ON public.%I (%I)',
        idx.index_name,
        idx.table_name,
        idx.column_name
      );
    END IF;
  END LOOP;
END $$;
