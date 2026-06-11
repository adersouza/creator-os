-- Reconstructed from schema_migrations on prod (remote-only).
-- version: 20260407100648
-- applied-by: add_missing_composite_indexes migration row


DO $$
DECLARE
  index_spec record;
BEGIN
  IF to_regclass('public.auto_post_queue') IS NOT NULL THEN
    ALTER TABLE public.auto_post_queue
      ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ;
  END IF;

  FOR index_spec IN
    SELECT *
    FROM (VALUES
      (
        'auto_post_queue',
        ARRAY['account_id', 'posted_at', 'status'],
        'CREATE INDEX IF NOT EXISTS idx_auto_post_queue_account_published ON public.auto_post_queue(account_id, posted_at DESC) WHERE status = ''published'''
      ),
      (
        'auto_post_queue',
        ARRAY['claimed_at', 'status'],
        'CREATE INDEX IF NOT EXISTS idx_auto_post_queue_stale_claims ON public.auto_post_queue(claimed_at ASC) WHERE status = ''publishing'''
      ),
      (
        'competitor_top_posts',
        ARRAY['competitor_id', 'engagement_score'],
        'CREATE INDEX IF NOT EXISTS idx_competitor_top_posts_comp_engagement ON public.competitor_top_posts(competitor_id, engagement_score DESC)'
      ),
      (
        'competitor_snapshots',
        ARRAY['competitor_id', 'snapshot_date'],
        'CREATE INDEX IF NOT EXISTS idx_competitor_snapshots_comp_date ON public.competitor_snapshots(competitor_id, snapshot_date DESC)'
      ),
      (
        'competitor_top_posts',
        ARRAY['created_at', 'enriched_at'],
        'CREATE INDEX IF NOT EXISTS idx_competitor_top_posts_needs_enrichment ON public.competitor_top_posts(created_at ASC) WHERE enriched_at IS NULL'
      )
    ) AS spec(table_name, required_columns, ddl)
  LOOP
    IF to_regclass(format('public.%I', index_spec.table_name)) IS NOT NULL
       AND NOT EXISTS (
         SELECT 1
         FROM unnest(index_spec.required_columns) AS required_column(column_name)
         WHERE NOT EXISTS (
           SELECT 1
           FROM information_schema.columns c
           WHERE c.table_schema = 'public'
             AND c.table_name = index_spec.table_name
             AND c.column_name = required_column.column_name
         )
       ) THEN
      EXECUTE index_spec.ddl;
    END IF;
  END LOOP;
END $$;
