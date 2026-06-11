-- Kill Dead Features Migration
-- Drops 8 feature clusters (16 tables) with zero users, zero data, zero API calls in 90 days.
-- All code references removed in companion commit. Safe to apply after code deploy.
--
-- Clusters: Engagement Pods, A/B Testing, Goals, Product Catalogs,
--           Saved Searches, Watermarks, Content Repurposing, RSS Pipeline

-- Pre-check: assert all tables are empty
DO $$
DECLARE
  tbl TEXT;
  cnt BIGINT;
BEGIN
  FOREACH tbl IN ARRAY ARRAY[
    'engagement_pods','pod_members','pod_posts','pod_engagements',
    'ab_tests','ab_test_variants',
    'user_goals','goal_history_snapshots',
    'product_catalogs','product_tags',
    'saved_searches','saved_search_snapshots',
    'watermark_configs','content_repurposing',
    'rss_feeds','rss_entries'
  ] LOOP
    EXECUTE format('SELECT count(*) FROM %I', tbl) INTO cnt;
    IF cnt > 0 THEN
      RAISE EXCEPTION 'Table % has % rows — aborting migration', tbl, cnt;
    END IF;
  END LOOP;
END $$;

-- ══════════════════════════════════════════════════════════════
-- 1. Drop RLS policies (must drop before tables)
-- ══════════════════════════════════════════════════════════════

-- Engagement Pods
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

-- A/B Testing
DROP POLICY IF EXISTS "Users can manage their own tests" ON ab_tests;
DROP POLICY IF EXISTS "Users can manage variants of their tests" ON ab_test_variants;

-- Content Repurposing
DROP POLICY IF EXISTS "Users can manage their own repurposed content" ON content_repurposing;

-- RSS
DROP POLICY IF EXISTS "Users manage own RSS feeds" ON rss_feeds;
DROP POLICY IF EXISTS "Users manage own RSS entries" ON rss_entries;

-- Saved Searches
DROP POLICY IF EXISTS "rls_user_saved_searches" ON saved_searches;
DROP POLICY IF EXISTS "rls_user_saved_search_snapshots" ON saved_search_snapshots;

-- Watermarks
DROP POLICY IF EXISTS "Users manage own watermarks" ON watermark_configs;

-- ══════════════════════════════════════════════════════════════
-- 2. Drop DB functions tied to dead features
-- ══════════════════════════════════════════════════════════════

DROP FUNCTION IF EXISTS update_saved_searches_updated_at() CASCADE;

-- ══════════════════════════════════════════════════════════════
-- 3. Drop tables (children first, parents last — CASCADE handles FKs)
-- ══════════════════════════════════════════════════════════════

-- Engagement Pods (children → parent)
DROP TABLE IF EXISTS pod_engagements CASCADE;
DROP TABLE IF EXISTS pod_posts CASCADE;
DROP TABLE IF EXISTS pod_members CASCADE;
DROP TABLE IF EXISTS engagement_pods CASCADE;

-- A/B Testing
DROP TABLE IF EXISTS ab_test_variants CASCADE;
DROP TABLE IF EXISTS ab_tests CASCADE;

-- Goals (may already be dropped by audit #10 migration)
DROP TABLE IF EXISTS goal_history_snapshots CASCADE;
DROP TABLE IF EXISTS user_goals CASCADE;

-- Product Catalogs
DROP TABLE IF EXISTS product_tags CASCADE;
DROP TABLE IF EXISTS product_catalogs CASCADE;

-- Saved Searches
DROP TABLE IF EXISTS saved_search_snapshots CASCADE;
DROP TABLE IF EXISTS saved_searches CASCADE;

-- Watermarks
DROP TABLE IF EXISTS watermark_configs CASCADE;

-- Content Repurposing
DROP TABLE IF EXISTS content_repurposing CASCADE;

-- RSS Pipeline
DROP TABLE IF EXISTS rss_entries CASCADE;
DROP TABLE IF EXISTS rss_feeds CASCADE;
