-- Backfilled from DB migration history. Some tables existed only in production
-- drift, so clean branch replay must skip indexes whose tables/columns are absent.
DO $$
DECLARE
  rec RECORD;
BEGIN
  FOR rec IN
    SELECT * FROM (VALUES
      ('idx_ab_test_variants_test_id', 'ab_test_variants', 'test_id'),
      ('idx_account_groups_user_id', 'account_groups', 'user_id'),
      ('idx_anomaly_alerts_instagram_account_id', 'anomaly_alerts', 'instagram_account_id'),
      ('idx_auto_post_activity_group_id', 'auto_post_activity', 'group_id'),
      ('idx_auto_post_activity_queue_item_id', 'auto_post_activity', 'queue_item_id'),
      ('idx_auto_post_group_config_group_id', 'auto_post_group_config', 'group_id'),
      ('idx_auto_post_group_state_group_id', 'auto_post_group_state', 'group_id'),
      ('idx_auto_post_queue_account_id', 'auto_post_queue', 'account_id'),
      ('idx_auto_post_queue_group_id', 'auto_post_queue', 'group_id'),
      ('idx_auto_reply_logs_account_id', 'auto_reply_logs', 'account_id'),
      ('idx_auto_reply_logs_rule_id', 'auto_reply_logs', 'rule_id'),
      ('idx_auto_reply_rules_account_id', 'auto_reply_rules', 'account_id'),
      ('idx_competitor_alerts_competitor_id', 'competitor_alerts', 'competitor_id'),
      ('idx_content_repurposing_user_id', 'content_repurposing', 'user_id'),
      ('idx_domain_verifications_user_id', 'domain_verifications', 'user_id'),
      ('idx_favorites_user_id', 'favorites', 'user_id'),
      ('idx_goal_history_snapshots_goal_id', 'goal_history_snapshots', 'goal_id'),
      ('idx_goal_history_snapshots_user_id', 'goal_history_snapshots', 'user_id'),
      ('idx_group_analytics_user_id', 'group_analytics', 'user_id'),
      ('idx_ig_auto_responders_template_id', 'ig_auto_responders', 'template_id'),
      ('idx_ig_auto_responders_user_id', 'ig_auto_responders', 'user_id'),
      ('idx_ig_auto_response_log_auto_responder_id', 'ig_auto_response_log', 'auto_responder_id'),
      ('idx_inbox_assignments_assigned_to', 'inbox_assignments', 'assigned_to'),
      ('idx_inspiration_config_workspace_id', 'inspiration_config', 'workspace_id'),
      ('idx_link_clicks_link_id', 'link_clicks', 'link_id'),
      ('idx_link_clicks_page_id', 'link_clicks', 'page_id'),
      ('idx_link_items_page_id', 'link_items', 'page_id'),
      ('idx_link_items_target_smart_link_id', 'link_items', 'target_smart_link_id'),
      ('idx_listening_alerts_user_id', 'listening_alerts', 'user_id'),
      ('idx_listening_results_alert_id', 'listening_results', 'alert_id'),
      ('idx_media_folder_id', 'media', 'folder_id'),
      ('idx_media_user_id', 'media', 'user_id'),
      ('idx_media_folders_user_id', 'media_folders', 'user_id'),
      ('idx_posts_draft_folder_id', 'posts', 'draft_folder_id'),
      ('idx_posts_rejected_by', 'posts', 'rejected_by'),
      ('idx_profiles_referred_by', 'profiles', 'referred_by'),
      ('idx_queue_slots_account_id', 'queue_slots', 'account_id'),
      ('idx_queue_slots_user_id', 'queue_slots', 'user_id'),
      ('idx_quick_wins_user_id', 'quick_wins', 'user_id'),
      ('idx_referral_codes_user_id', 'referral_codes', 'user_id'),
      ('idx_referrals_referral_code_id', 'referrals', 'referral_code_id'),
      ('idx_rss_feeds_account_id', 'rss_feeds', 'account_id'),
      ('idx_rss_feeds_ig_account_id', 'rss_feeds', 'instagram_account_id'),
      ('idx_rss_feeds_workspace_id', 'rss_feeds', 'workspace_id'),
      ('idx_sent_replies_account_id', 'sent_replies', 'account_id'),
      ('idx_sent_replies_user_id', 'sent_replies', 'user_id'),
      ('idx_smart_link_clicks_smart_link_id', 'smart_link_clicks', 'smart_link_id'),
      ('idx_smart_link_conversions_click_id', 'smart_link_conversions', 'click_id'),
      ('idx_sync_jobs_user_id', 'sync_jobs', 'user_id'),
      ('idx_trend_forecasts_account_id', 'trend_forecasts', 'account_id'),
      ('idx_unified_links_workspace_id', 'unified_links', 'workspace_id'),
      ('idx_user_goals_user_id', 'user_goals', 'user_id'),
      ('idx_webhook_deliveries_user_id', 'webhook_deliveries', 'user_id'),
      ('idx_workspace_invites_invited_by', 'workspace_invites', 'invited_by'),
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
