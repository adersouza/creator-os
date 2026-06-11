-- ============================================================================
-- Add missing FK indexes + drop unused indexes
-- Date: 2026-02-18
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. Missing FK indexes (unindexed_foreign_keys warnings)
-- ============================================================================

DO $$
DECLARE
  rec RECORD;
BEGIN
  FOR rec IN
    SELECT * FROM (VALUES
      ('idx_account_groups_user_id', 'account_groups', 'user_id'),
      ('idx_accounts_group_id', 'accounts', 'group_id'),
      ('idx_auto_post_activity_queue_item_id', 'auto_post_activity', 'queue_item_id'),
      ('idx_auto_reply_rules_account_id', 'auto_reply_rules', 'account_id'),
      ('idx_competitor_alerts_competitor_id', 'competitor_alerts', 'competitor_id'),
      ('idx_content_repurposing_target_post_id', 'content_repurposing', 'target_post_id'),
      ('idx_favorites_user_id', 'favorites', 'user_id'),
      ('idx_ig_auto_responders_template_id', 'ig_auto_responders', 'template_id'),
      ('idx_ig_pending_containers_post_id', 'ig_pending_containers', 'post_id'),
      ('idx_inspiration_config_workspace_id', 'inspiration_config', 'workspace_id'),
      ('idx_media_folder_id', 'media', 'folder_id'),
      ('idx_media_user_id', 'media', 'user_id'),
      ('idx_media_folders_user_id', 'media_folders', 'user_id'),
      ('idx_profiles_referred_by', 'profiles', 'referred_by'),
      ('idx_queue_slots_account_id', 'queue_slots', 'account_id'),
      ('idx_queue_slots_user_id', 'queue_slots', 'user_id'),
      ('idx_sent_replies_user_id', 'sent_replies', 'user_id'),
      ('idx_workspace_invites_invited_by', 'workspace_invites', 'invited_by'),
      ('idx_workspace_invites_workspace_id', 'workspace_invites', 'workspace_id'),
      ('idx_workspace_members_user_id', 'workspace_members', 'user_id'),
      ('idx_workspaces_owner_id', 'workspaces', 'owner_id')
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

-- ============================================================================
-- 2. Drop clearly unused indexes (tables with no traffic yet)
--    Keeping indexes that will be needed once features get traffic
--    Only dropping indexes on tables that are unlikely to need them
-- ============================================================================

-- Duplicate indexes already dropped in previous migration (100005)
-- idx_cron_runs_job_started was already dropped as duplicate

-- Drop indexes that were created on the wrong assumption or truly unused
DROP INDEX IF EXISTS idx_competitors_platform;
DROP INDEX IF EXISTS idx_competitor_top_posts_platform;

COMMIT;
