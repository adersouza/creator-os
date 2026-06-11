-- Backfilled from DB migration history
-- Drops 13 remaining tables from 8 dead feature clusters (v2 — excludes already-dropped)
DO $$ DECLARE tbl TEXT; cnt BIGINT;
BEGIN
  FOREACH tbl IN ARRAY ARRAY['engagement_pods','pod_members','pod_posts','pod_engagements',
    'ab_tests','ab_test_variants','product_catalogs','saved_searches','saved_search_snapshots',
    'watermark_configs','content_repurposing','rss_feeds','rss_entries'] LOOP
    EXECUTE format('SELECT count(*) FROM %I', tbl) INTO cnt;
    IF cnt > 0 THEN RAISE EXCEPTION 'Table % has % rows', tbl, cnt; END IF;
  END LOOP;
END $$;
DROP POLICY IF EXISTS "Pod members and owners see pods" ON engagement_pods;
DROP POLICY IF EXISTS "Owners insert pods" ON engagement_pods;
DROP POLICY IF EXISTS "Owners update pods" ON engagement_pods;
DROP POLICY IF EXISTS "Owners delete pods" ON engagement_pods;
DROP POLICY IF EXISTS "Pod members see engagements" ON pod_engagements;
DROP POLICY IF EXISTS "Members record engagements" ON pod_engagements;
DROP POLICY IF EXISTS "Pod members see members" ON pod_members;
DROP POLICY IF EXISTS "Users insert own membership" ON pod_members;
DROP POLICY IF EXISTS "Users update own membership" ON pod_members;
DROP POLICY IF EXISTS "Users delete own membership" ON pod_members;
DROP POLICY IF EXISTS "Members submit posts" ON pod_posts;
DROP POLICY IF EXISTS "Pod members see posts" ON pod_posts;
DROP POLICY IF EXISTS "Users can manage their own tests" ON ab_tests;
DROP POLICY IF EXISTS "Users can manage variants of their tests" ON ab_test_variants;
DROP POLICY IF EXISTS "Users can manage their own repurposed content" ON content_repurposing;
DROP POLICY IF EXISTS "Users manage own RSS feeds" ON rss_feeds;
DROP POLICY IF EXISTS "Users manage own RSS entries" ON rss_entries;
DROP POLICY IF EXISTS "rls_user_saved_searches" ON saved_searches;
DROP POLICY IF EXISTS "rls_user_saved_search_snapshots" ON saved_search_snapshots;
DROP POLICY IF EXISTS "Users manage own watermarks" ON watermark_configs;
DROP FUNCTION IF EXISTS update_saved_searches_updated_at() CASCADE;
DROP TABLE IF EXISTS pod_engagements CASCADE;
DROP TABLE IF EXISTS pod_posts CASCADE;
DROP TABLE IF EXISTS pod_members CASCADE;
DROP TABLE IF EXISTS engagement_pods CASCADE;
DROP TABLE IF EXISTS ab_test_variants CASCADE;
DROP TABLE IF EXISTS ab_tests CASCADE;
DROP TABLE IF EXISTS product_catalogs CASCADE;
DROP TABLE IF EXISTS saved_search_snapshots CASCADE;
DROP TABLE IF EXISTS saved_searches CASCADE;
DROP TABLE IF EXISTS watermark_configs CASCADE;
DROP TABLE IF EXISTS content_repurposing CASCADE;
DROP TABLE IF EXISTS rss_entries CASCADE;
DROP TABLE IF EXISTS rss_feeds CASCADE;
