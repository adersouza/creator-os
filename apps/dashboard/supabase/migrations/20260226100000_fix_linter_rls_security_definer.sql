-- Fix Supabase linter findings:
-- 1. unified_link_roi: SECURITY DEFINER → security_invoker = on
-- 2. unified_links: RLS enabled but no policies
-- 3. link_benchmarks: RLS enabled but no policies
-- stripe_processed_events left as-is (service-role-only by design)

-- ============================================================
-- 1. Recreate unified_link_roi with security_invoker = on
--    Without this, the view runs as the owner, bypassing RLS
--    on the underlying tables (link_pages, link_items, smart_links).
-- ============================================================
DROP VIEW IF EXISTS unified_link_roi;

CREATE VIEW unified_link_roi
WITH (security_invoker = on) AS
SELECT
    lp.user_id,
    lp.id AS page_id,
    lp.title AS page_title,
    lp.view_count AS page_views,
    (SELECT COUNT(*) FROM link_items li WHERE li.page_id = lp.id) AS button_count,
    COALESCE(SUM(sl.click_count), 0) AS total_redirect_clicks,
    COALESCE(SUM(sl.est_conversion_value * sl.click_count * sl.est_conversion_rate), 0) AS estimated_revenue
FROM link_pages lp
LEFT JOIN link_items li ON li.page_id = lp.id
LEFT JOIN smart_links sl ON sl.id = li.target_smart_link_id
GROUP BY lp.id, lp.user_id, lp.title, lp.view_count;

-- ============================================================
-- 2. unified_links — user-owned rows, standard CRUD policies
-- ============================================================
ALTER TABLE unified_links ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  CREATE POLICY "Users can view own unified_links"
      ON unified_links FOR SELECT
      USING (auth.uid()::text = user_id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE POLICY "Users can insert own unified_links"
      ON unified_links FOR INSERT
      WITH CHECK (auth.uid()::text = user_id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE POLICY "Users can update own unified_links"
      ON unified_links FOR UPDATE
      USING (auth.uid()::text = user_id)
      WITH CHECK (auth.uid()::text = user_id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE POLICY "Users can delete own unified_links"
      ON unified_links FOR DELETE
      USING (auth.uid()::text = user_id);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ============================================================
-- 3. link_benchmarks — read-only reference data for all users
-- ============================================================
ALTER TABLE link_benchmarks ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  CREATE POLICY "Authenticated users can read benchmarks"
      ON link_benchmarks FOR SELECT
      USING (auth.role() = 'authenticated');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
