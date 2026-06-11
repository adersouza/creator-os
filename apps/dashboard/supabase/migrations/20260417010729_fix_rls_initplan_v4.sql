-- Fix Supabase linter warning auth_rls_initplan (2026-04-16):
-- Wrap bare auth.uid() in (SELECT auth.uid()) so Postgres evaluates the call
-- once per query (initPlan) instead of once per row. 100x speedup on
-- analytics JOINs and list queries.
--
-- v3 (2026-04-02) covered 7 policies. Live pg_policies audit found 11 still
-- unwrapped on tables created after v3:
--   public: chart_annotations, demographics_snapshots, inbox_dm_messages,
--           post_tags, report_schedules, share_of_voice_history,
--           shared_reports, shield_log, user_tag_palette
--   storage.objects: Users can upload to own folder, Users can delete own files
--
-- Post-apply: 0 unwrapped expected. Verification query at file end.

-- ============================================================================
-- public schema (9 policies)
-- ============================================================================

-- chart_annotations
DROP POLICY IF EXISTS "Users manage own annotations" ON public.chart_annotations;
CREATE POLICY "Users manage own annotations" ON public.chart_annotations
  FOR ALL
  USING ((SELECT auth.uid())::text = user_id)
  WITH CHECK ((SELECT auth.uid())::text = user_id);

-- demographics_snapshots
DROP POLICY IF EXISTS "Users access own demographics" ON public.demographics_snapshots;
CREATE POLICY "Users access own demographics" ON public.demographics_snapshots
  FOR ALL
  USING ((SELECT auth.uid())::text = user_id)
  WITH CHECK ((SELECT auth.uid())::text = user_id);

-- inbox_dm_messages
DROP POLICY IF EXISTS "Users can read own DM messages" ON public.inbox_dm_messages;
CREATE POLICY "Users can read own DM messages" ON public.inbox_dm_messages
  FOR SELECT
  USING ((SELECT auth.uid())::text = user_id);

-- post_tags
DROP POLICY IF EXISTS "Users manage own post tags" ON public.post_tags;
CREATE POLICY "Users manage own post tags" ON public.post_tags
  FOR ALL
  USING ((SELECT auth.uid())::text = user_id)
  WITH CHECK ((SELECT auth.uid())::text = user_id);

-- report_schedules
DROP POLICY IF EXISTS "Users manage own report schedules" ON public.report_schedules;
CREATE POLICY "Users manage own report schedules" ON public.report_schedules
  FOR ALL
  USING ((SELECT auth.uid())::text = user_id)
  WITH CHECK ((SELECT auth.uid())::text = user_id);

-- share_of_voice_history
DROP POLICY IF EXISTS "Users access own SoV history" ON public.share_of_voice_history;
CREATE POLICY "Users access own SoV history" ON public.share_of_voice_history
  FOR ALL
  USING ((SELECT auth.uid())::text = user_id)
  WITH CHECK ((SELECT auth.uid())::text = user_id);

-- shared_reports
DROP POLICY IF EXISTS "Users manage own shared reports" ON public.shared_reports;
CREATE POLICY "Users manage own shared reports" ON public.shared_reports
  FOR ALL
  USING ((SELECT auth.uid())::text = user_id)
  WITH CHECK ((SELECT auth.uid())::text = user_id);

-- shield_log (subquery via link_pages)
DROP POLICY IF EXISTS "shield_log_select" ON public.shield_log;
CREATE POLICY "shield_log_select" ON public.shield_log
  FOR SELECT
  USING (
    page_id IN (
      SELECT link_pages.id FROM public.link_pages
      WHERE link_pages.user_id = (SELECT auth.uid())::text
    )
  );

-- user_tag_palette
DROP POLICY IF EXISTS "Users manage own tag palette" ON public.user_tag_palette;
CREATE POLICY "Users manage own tag palette" ON public.user_tag_palette
  FOR ALL
  USING ((SELECT auth.uid())::text = user_id)
  WITH CHECK ((SELECT auth.uid())::text = user_id);

-- ============================================================================
-- storage.objects (2 policies — media bucket)
-- These are hit on every media read/write. Highest-ROI fix in this batch.
-- ============================================================================

DROP POLICY IF EXISTS "Users can upload to own folder" ON storage.objects;
CREATE POLICY "Users can upload to own folder" ON storage.objects
  FOR INSERT TO authenticated
  WITH CHECK (
    bucket_id = 'media'
    AND (SELECT auth.uid())::text = (storage.foldername(name))[1]
  );

DROP POLICY IF EXISTS "Users can delete own files" ON storage.objects;
CREATE POLICY "Users can delete own files" ON storage.objects
  FOR DELETE TO authenticated
  USING (
    bucket_id = 'media'
    AND (SELECT auth.uid())::text = (storage.foldername(name))[1]
  );

-- ============================================================================
-- Verification (run manually after apply):
--   SELECT COUNT(*) FROM pg_policies
--   WHERE schemaname IN ('public','storage')
--     AND regexp_replace(
--           COALESCE(qual,'') || ' ' || COALESCE(with_check,''),
--           '\(\s*SELECT\s+auth\.\w+\s*\(\s*\)(\s+AS\s+\w+)?\s*\)',
--           'WRAPPED', 'gi'
--         ) ~* 'auth\.\w+\s*\(';
-- Expected: 0
-- ============================================================================
