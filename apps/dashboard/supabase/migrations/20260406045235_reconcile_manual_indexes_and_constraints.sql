-- Reconstructed from schema_migrations on prod (remote-only).
-- version: 20260406045235
-- applied-by: reconcile_manual_indexes_and_constraints migration row


-- =============================================================================
-- Migration: Reconcile 62 manually-created indexes + 1 unique constraint
-- These exist in the live DB but were never tracked in migrations.
-- All use IF NOT EXISTS so this is safe to replay.
-- =============================================================================

DO $$
DECLARE
  ddl text;
BEGIN
  FOREACH ddl IN ARRAY ARRAY[
    'CREATE INDEX IF NOT EXISTS account_analytics_date_idx ON public.account_analytics USING btree (date)',
    'CREATE INDEX IF NOT EXISTS account_daily_summary_date_idx ON public.account_daily_summary USING btree (date)',
    'CREATE INDEX IF NOT EXISTS accounts_created_at_idx ON public.accounts USING btree (created_at)',
    'CREATE INDEX IF NOT EXISTS idx_account_health_snapshots_platform ON public.account_health_snapshots USING btree (platform)',
    'CREATE INDEX IF NOT EXISTS idx_account_health_snapshots_workspace_id ON public.account_health_snapshots USING btree (workspace_id)',
    'CREATE INDEX IF NOT EXISTS idx_accounts_is_active ON public.accounts USING btree (is_active)',
    'CREATE INDEX IF NOT EXISTS idx_ai_config_user_id ON public.ai_config USING btree (user_id)',
    'CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id ON public.audit_logs USING btree (user_id)',
    'CREATE INDEX IF NOT EXISTS idx_auto_cross_replies_workspace_id ON public.auto_cross_replies USING btree (workspace_id)',
    'CREATE INDEX IF NOT EXISTS idx_auto_post_activity_workspace_id ON public.auto_post_activity USING btree (workspace_id)',
    'CREATE INDEX IF NOT EXISTS idx_auto_post_config_is_enabled ON public.auto_post_config USING btree (is_enabled)',
    'CREATE INDEX IF NOT EXISTS idx_auto_post_queue_workspace_id ON public.auto_post_queue USING btree (workspace_id)',
    'CREATE INDEX IF NOT EXISTS idx_auto_post_state_workspace_id ON public.auto_post_state USING btree (workspace_id)',
    'CREATE INDEX IF NOT EXISTS idx_auto_self_replies_account_id ON public.auto_self_replies USING btree (account_id)',
    'CREATE INDEX IF NOT EXISTS idx_auto_self_replies_workspace_id ON public.auto_self_replies USING btree (workspace_id)',
    'CREATE INDEX IF NOT EXISTS idx_competitor_snapshots_competitor_id ON public.competitor_snapshots USING btree (competitor_id)',
    'CREATE INDEX IF NOT EXISTS idx_competitor_top_posts_competitor_id ON public.competitor_top_posts USING btree (competitor_id)',
    'CREATE INDEX IF NOT EXISTS idx_competitor_top_posts_engagement ON public.competitor_top_posts USING btree (engagement_score DESC)',
    'CREATE INDEX IF NOT EXISTS idx_competitor_top_posts_platform ON public.competitor_top_posts USING btree (platform)',
    'CREATE INDEX IF NOT EXISTS idx_competitor_top_posts_published_at ON public.competitor_top_posts USING btree (published_at)',
    'CREATE INDEX IF NOT EXISTS idx_crisis_events_post_id ON public.crisis_events USING btree (post_id)',
    'CREATE INDEX IF NOT EXISTS idx_crisis_events_workspace_id ON public.crisis_events USING btree (workspace_id)',
    'CREATE INDEX IF NOT EXISTS idx_favorites_post_id ON public.favorites USING btree (post_id)',
    'CREATE INDEX IF NOT EXISTS idx_ig_auto_responders_account ON public.ig_auto_responders USING btree (ig_account_id)',
    'CREATE INDEX IF NOT EXISTS idx_ig_auto_responders_enabled ON public.ig_auto_responders USING btree (ig_account_id, is_enabled) WHERE (is_enabled = true)',
    'CREATE INDEX IF NOT EXISTS idx_ig_collab_invites_account_id ON public.ig_collab_invites USING btree (account_id)',
    'CREATE INDEX IF NOT EXISTS idx_ig_comments_account_id ON public.ig_comments USING btree (account_id)',
    'CREATE INDEX IF NOT EXISTS idx_ig_pending_containers_account_id ON public.ig_pending_containers USING btree (account_id)',
    'CREATE INDEX IF NOT EXISTS idx_ig_pending_containers_status ON public.ig_pending_containers USING btree (status)',
    'CREATE INDEX IF NOT EXISTS idx_influencer_collabs_workspace_id ON public.influencer_collabs USING btree (workspace_id)',
    'CREATE INDEX IF NOT EXISTS idx_inspiration_config_user_id ON public.inspiration_config USING btree (user_id)',
    'CREATE INDEX IF NOT EXISTS idx_inspiration_ideas_competitor_id ON public.inspiration_ideas USING btree (competitor_id)',
    'CREATE INDEX IF NOT EXISTS idx_inspiration_ideas_generated_at ON public.inspiration_ideas USING btree (generated_at DESC)',
    'CREATE INDEX IF NOT EXISTS idx_inspiration_ideas_status ON public.inspiration_ideas USING btree (status)',
    'CREATE INDEX IF NOT EXISTS idx_inspiration_ideas_user_id ON public.inspiration_ideas USING btree (user_id)',
    'CREATE INDEX IF NOT EXISTS idx_inspiration_ideas_viral_score ON public.inspiration_ideas USING btree (viral_score DESC)',
    'CREATE INDEX IF NOT EXISTS idx_inspiration_ideas_workspace_id ON public.inspiration_ideas USING btree (workspace_id)',
    'CREATE INDEX IF NOT EXISTS idx_listening_results_workspace_id ON public.listening_results USING btree (workspace_id)',
    'CREATE INDEX IF NOT EXISTS idx_mentions_user_id ON public.mentions USING btree (user_id)',
    'CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON public.notifications USING btree (user_id)',
    'CREATE INDEX IF NOT EXISTS idx_post_replies_post_id ON public.post_replies USING btree (post_id)',
    'CREATE INDEX IF NOT EXISTS idx_posts_approval_status ON public.posts USING btree (approval_status)',
    'CREATE INDEX IF NOT EXISTS idx_posts_ig_container_pending ON public.posts USING btree (ig_container_id, ig_container_status) WHERE ((ig_container_id IS NOT NULL) AND (status = ''publishing''::text))',
    'CREATE INDEX IF NOT EXISTS idx_saved_competitor_posts_user_id ON public.saved_competitor_posts USING btree (user_id)',
    'CREATE INDEX IF NOT EXISTS idx_threads_webhook_events_type ON public.threads_webhook_events USING btree (event_type, received_at DESC)',
    'CREATE INDEX IF NOT EXISTS idx_threads_webhook_events_unprocessed ON public.threads_webhook_events USING btree (processed, received_at) WHERE (processed = false)',
    'CREATE INDEX IF NOT EXISTS idx_trend_keywords_user_id ON public.trend_keywords USING btree (user_id)',
    'CREATE INDEX IF NOT EXISTS idx_trend_posts_user_id ON public.trend_posts USING btree (user_id)',
    'CREATE INDEX IF NOT EXISTS idx_trend_snapshots_user_id ON public.trend_snapshots USING btree (user_id)',
    'CREATE INDEX IF NOT EXISTS idx_user_preferences_user_id ON public.user_preferences USING btree (user_id)',
    'CREATE INDEX IF NOT EXISTS idx_workspace_activity_user_id ON public.workspace_activity USING btree (user_id)',
    'CREATE INDEX IF NOT EXISTS idx_workspace_activity_workspace_id ON public.workspace_activity USING btree (workspace_id)',
    'CREATE INDEX IF NOT EXISTS instagram_accounts_created_at_idx ON public.instagram_accounts USING btree (created_at)',
    'CREATE UNIQUE INDEX IF NOT EXISTS agent_notes_user_key_group_idx ON public.agent_notes USING btree (user_id, key, COALESCE(account_group_id, ''__global__''::text))',
    'CREATE UNIQUE INDEX IF NOT EXISTS competitors_user_username_platform_unique ON public.competitors USING btree (user_id, username, platform)',
    'CREATE UNIQUE INDEX IF NOT EXISTS idx_ig_dm_templates_shortcut ON public.ig_dm_templates USING btree (user_id, shortcut) WHERE (shortcut IS NOT NULL)',
    'CREATE UNIQUE INDEX IF NOT EXISTS idx_posts_threads_user ON public.posts USING btree (threads_post_id, user_id) WHERE (threads_post_id IS NOT NULL)',
    'CREATE UNIQUE INDEX IF NOT EXISTS revenue_snapshots_group_date_idx ON public.revenue_snapshots USING btree (user_id, account_group_id, recorded_at)',
    'CREATE UNIQUE INDEX IF NOT EXISTS trend_discoveries_account_group_id_topic_hash_unique ON public.trend_discoveries USING btree (account_group_id, topic_hash)',
    'CREATE UNIQUE INDEX IF NOT EXISTS uq_account_analytics_account_date ON public.account_analytics USING btree (account_id, date)',
    'CREATE UNIQUE INDEX IF NOT EXISTS uq_posts_user_instagram_post_id ON public.posts USING btree (user_id, instagram_post_id)',
    'CREATE UNIQUE INDEX IF NOT EXISTS uq_smart_link_conversions_order ON public.smart_link_conversions USING btree (smart_link_id, order_id)',
    'CREATE UNIQUE INDEX IF NOT EXISTS competitor_snapshots_competitor_id_snapshot_date_key ON public.competitor_snapshots USING btree (competitor_id, snapshot_date)'
  ]
  LOOP
    BEGIN
      EXECUTE ddl;
    EXCEPTION
      WHEN undefined_table
        OR undefined_column
        OR duplicate_table
        OR invalid_object_definition
        OR datatype_mismatch THEN
        RAISE NOTICE 'Skipping replay-unsafe index DDL: %: %', ddl, SQLERRM;
    END;
  END LOOP;
END $$;

-- ===== RPC Function: get_post_floor_aggregates =====
DO $$
BEGIN
  IF to_regclass('public.posts') IS NOT NULL
     AND NOT EXISTS (
       SELECT 1
       FROM unnest(ARRAY[
         'views_count',
         'likes_count',
         'replies_count',
         'shares_count',
         'user_id',
         'status',
         'published_at',
         'platform',
         'account_id'
       ]) AS required_column(column_name)
       WHERE NOT EXISTS (
         SELECT 1
         FROM information_schema.columns c
         WHERE c.table_schema = 'public'
           AND c.table_name = 'posts'
           AND c.column_name = required_column.column_name
       )
     ) THEN
    EXECUTE $fn$
      CREATE OR REPLACE FUNCTION public.get_post_floor_aggregates(
        p_user_id text,
        p_account_ids text[],
        p_since timestamp with time zone,
        p_platform text DEFAULT NULL::text
      )
       RETURNS TABLE(total_views bigint, total_likes bigint, total_replies bigint, total_shares bigint, post_count bigint)
       LANGUAGE sql
       STABLE SECURITY DEFINER
       SET search_path TO 'public'
      AS $function$
        SELECT
          COALESCE(SUM(views_count), 0)::bigint,
          COALESCE(SUM(likes_count), 0)::bigint,
          COALESCE(SUM(replies_count), 0)::bigint,
          COALESCE(SUM(shares_count), 0)::bigint,
          COUNT(*)::bigint
        FROM posts
        WHERE user_id = p_user_id
          AND status = 'published'
          AND published_at IS NOT NULL
          AND published_at >= p_since
          AND (
            (p_platform = 'instagram' AND platform = 'instagram')
            OR (p_platform IS NULL AND account_id = ANY(p_account_ids))
            OR (p_platform != 'instagram' AND account_id = ANY(p_account_ids))
          );
      $function$;
    $fn$;
  END IF;
END $$;
