-- Fix auth_rls_initplan for policies created in 20260226100000:
-- unified_links (4 policies) and link_benchmarks (1 policy)

-- ============================================================
-- 1. unified_links — wrap auth.uid() in (select ...)
-- ============================================================
DROP POLICY IF EXISTS "Users can view own unified_links" ON unified_links;
CREATE POLICY "Users can view own unified_links"
    ON unified_links FOR SELECT
    USING ((select auth.uid())::text = user_id);

DROP POLICY IF EXISTS "Users can insert own unified_links" ON unified_links;
CREATE POLICY "Users can insert own unified_links"
    ON unified_links FOR INSERT
    WITH CHECK ((select auth.uid())::text = user_id);

DROP POLICY IF EXISTS "Users can update own unified_links" ON unified_links;
CREATE POLICY "Users can update own unified_links"
    ON unified_links FOR UPDATE
    USING ((select auth.uid())::text = user_id)
    WITH CHECK ((select auth.uid())::text = user_id);

DROP POLICY IF EXISTS "Users can delete own unified_links" ON unified_links;
CREATE POLICY "Users can delete own unified_links"
    ON unified_links FOR DELETE
    USING ((select auth.uid())::text = user_id);

-- ============================================================
-- 2. link_benchmarks — wrap auth.role() in (select ...)
-- ============================================================
DROP POLICY IF EXISTS "Authenticated users can read benchmarks" ON link_benchmarks;
CREATE POLICY "Authenticated users can read benchmarks"
    ON link_benchmarks FOR SELECT
    USING ((select auth.role()) = 'authenticated');
