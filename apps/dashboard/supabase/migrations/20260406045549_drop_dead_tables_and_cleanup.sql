-- Reconstructed from schema_migrations on prod (remote-only).
-- version: 20260406045549
-- applied-by: drop_dead_tables_and_cleanup migration row


-- =============================================================================
-- Drop orphaned tables with zero rows and no code references
-- Create missing view for export_jobs alias
-- =============================================================================

-- 1. competitor_posts: superseded by competitor_top_posts, 0 rows, no code refs
DO $$
DECLARE
  dependent_constraint record;
BEGIN
  IF to_regclass('public.competitor_posts') IS NOT NULL THEN
    FOR dependent_constraint IN
      SELECT conrelid::regclass AS table_name, conname
      FROM pg_constraint
      WHERE confrelid = 'public.competitor_posts'::regclass
    LOOP
      EXECUTE format(
        'ALTER TABLE %s DROP CONSTRAINT IF EXISTS %I',
        dependent_constraint.table_name,
        dependent_constraint.conname
      );
    END LOOP;
  END IF;
END $$;

DROP TABLE IF EXISTS competitor_posts;

-- 2. ig_auto_response_log: code uses ig_dm_ai_responses instead, 0 rows
DROP TABLE IF EXISTS ig_auto_response_log;

-- 3. export_jobs: code references this name but the actual table is data_export_jobs
-- Create a view alias so both names work
CREATE OR REPLACE VIEW export_jobs AS
  SELECT * FROM data_export_jobs;

-- 4. exports: code in export-worker.ts references this but it's the same as data_export_jobs
CREATE OR REPLACE VIEW exports AS
  SELECT * FROM data_export_jobs;
