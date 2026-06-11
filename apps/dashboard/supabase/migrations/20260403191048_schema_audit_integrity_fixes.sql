-- Reconstructed from schema_migrations on prod (remote-only).
-- version: 20260403191048
-- applied-by: schema_audit_integrity_fixes migration row

-- =============================================================================
-- SCHEMA AUDIT: Orphan cleanup, type fix, FK constraints, column drops
-- =============================================================================
-- Production had all of these objects when the audit was generated. Branch replay
-- can legitimately lack some historical tables/columns, so every operation below
-- checks the live schema before it runs.

DO $$
DECLARE
  cleanup record;
  fk record;
BEGIN
  FOR cleanup IN
    SELECT *
    FROM (VALUES
      ('account_analytics', 'account_id', 'accounts', 'id'),
      ('account_metrics_history', 'account_id', 'accounts', 'id'),
      ('account_health_snapshots', 'account_id', 'accounts', 'id'),
      ('auto_post_state', 'workspace_id', 'workspaces', 'id'),
      ('post_replies', 'post_id', 'posts', 'id'),
      ('favorites', 'post_id', 'posts', 'id')
    ) AS v(table_name, column_name, ref_table_name, ref_column_name)
  LOOP
    IF to_regclass(format('public.%I', cleanup.table_name)) IS NOT NULL
       AND to_regclass(format('public.%I', cleanup.ref_table_name)) IS NOT NULL
       AND EXISTS (
         SELECT 1
         FROM information_schema.columns c
         WHERE c.table_schema = 'public'
           AND c.table_name = cleanup.table_name
           AND c.column_name = cleanup.column_name
       )
       AND EXISTS (
         SELECT 1
         FROM information_schema.columns c
         WHERE c.table_schema = 'public'
           AND c.table_name = cleanup.ref_table_name
           AND c.column_name = cleanup.ref_column_name
       ) THEN
      EXECUTE format(
        'DELETE FROM public.%I child WHERE NOT EXISTS (SELECT 1 FROM public.%I parent WHERE parent.%I = child.%I)',
        cleanup.table_name,
        cleanup.ref_table_name,
        cleanup.ref_column_name,
        cleanup.column_name
      );
    END IF;
  END LOOP;

  IF to_regclass('public.auto_post_queue') IS NOT NULL
     AND EXISTS (
       SELECT 1
       FROM information_schema.columns c
       WHERE c.table_schema = 'public'
         AND c.table_name = 'auto_post_queue'
         AND c.column_name = 'source_competitor_id'
     ) THEN
    ALTER TABLE public.auto_post_queue
      ALTER COLUMN source_competitor_id TYPE text USING source_competitor_id::text;
  END IF;

  FOR fk IN
    SELECT *
    FROM (VALUES
      ('fk_account_analytics_account', 'account_analytics', 'account_id', 'accounts', 'id', 'CASCADE'),
      ('fk_account_metrics_history_account', 'account_metrics_history', 'account_id', 'accounts', 'id', 'CASCADE'),
      ('fk_account_health_snapshots_account', 'account_health_snapshots', 'account_id', 'accounts', 'id', 'CASCADE'),
      ('fk_account_health_snapshots_workspace', 'account_health_snapshots', 'workspace_id', 'workspaces', 'id', 'CASCADE'),
      ('fk_post_replies_post', 'post_replies', 'post_id', 'posts', 'id', 'CASCADE'),
      ('fk_mentions_account', 'mentions', 'account_id', 'accounts', 'id', 'CASCADE'),
      ('fk_mentions_user', 'mentions', 'user_id', 'profiles', 'id', 'CASCADE'),
      ('fk_favorites_post', 'favorites', 'post_id', 'posts', 'id', 'CASCADE'),
      ('fk_crisis_events_workspace', 'crisis_events', 'workspace_id', 'workspaces', 'id', 'CASCADE'),
      ('fk_crisis_events_post', 'crisis_events', 'post_id', 'posts', 'id', 'SET NULL'),
      ('fk_workspace_activity_user', 'workspace_activity', 'user_id', 'profiles', 'id', 'CASCADE'),
      ('fk_listening_results_workspace', 'listening_results', 'workspace_id', 'workspaces', 'id', 'CASCADE'),
      ('fk_media_group', 'media', 'group_id', 'account_groups', 'id', 'SET NULL'),
      ('fk_competitor_metrics_history_competitor', 'competitor_metrics_history', 'competitor_id', 'competitors', 'id', 'CASCADE'),
      ('fk_competitor_posts_competitor', 'competitor_posts', 'competitor_id', 'competitors', 'id', 'CASCADE'),
      ('fk_auto_post_state_workspace', 'auto_post_state', 'workspace_id', 'workspaces', 'id', 'CASCADE'),
      ('fk_influencer_collabs_workspace', 'influencer_collabs', 'workspace_id', 'workspaces', 'id', 'CASCADE')
    ) AS v(constraint_name, table_name, column_name, ref_table_name, ref_column_name, on_delete)
  LOOP
    IF to_regclass(format('public.%I', fk.table_name)) IS NOT NULL
       AND to_regclass(format('public.%I', fk.ref_table_name)) IS NOT NULL
       AND NOT EXISTS (
         SELECT 1
         FROM information_schema.table_constraints tc
         WHERE tc.table_schema = 'public'
           AND tc.table_name = fk.table_name
           AND tc.constraint_name = fk.constraint_name
       )
       AND EXISTS (
         SELECT 1
         FROM information_schema.columns c
         WHERE c.table_schema = 'public'
           AND c.table_name = fk.table_name
           AND c.column_name = fk.column_name
       )
       AND EXISTS (
         SELECT 1
         FROM information_schema.columns c
         WHERE c.table_schema = 'public'
           AND c.table_name = fk.ref_table_name
           AND c.column_name = fk.ref_column_name
       ) THEN
      BEGIN
        EXECUTE format(
          'ALTER TABLE public.%I ADD CONSTRAINT %I FOREIGN KEY (%I) REFERENCES public.%I(%I) ON DELETE %s NOT VALID',
          fk.table_name,
          fk.constraint_name,
          fk.column_name,
          fk.ref_table_name,
          fk.ref_column_name,
          fk.on_delete
        );

        EXECUTE format(
          'ALTER TABLE public.%I VALIDATE CONSTRAINT %I',
          fk.table_name,
          fk.constraint_name
        );
      EXCEPTION
        WHEN duplicate_object
          OR undefined_table
          OR undefined_column
          OR datatype_mismatch
          OR invalid_foreign_key
          OR foreign_key_violation THEN
          RAISE NOTICE 'Skipping replay-unsafe FK %.% -> %.%: %',
            fk.table_name, fk.column_name, fk.ref_table_name, fk.ref_column_name, SQLERRM;
      END;
    END IF;
  END LOOP;

  IF to_regclass('public.posts') IS NOT NULL THEN
    ALTER TABLE public.posts DROP COLUMN IF EXISTS spoofed;
    ALTER TABLE public.posts DROP COLUMN IF EXISTS spoof_techniques;
  END IF;

  IF to_regclass('public.rate_limit_tracking') IS NOT NULL THEN
    ALTER TABLE public.rate_limit_tracking
      DROP CONSTRAINT IF EXISTS rate_limit_tracking_account_id_fkey;
  END IF;
END $$;
