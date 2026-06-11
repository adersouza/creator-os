-- RLS hardening for older feature tables that predate the main RLS sweep.
-- These tables are user-owned and may be accessed by the client Supabase SDK,
-- so every policy is scoped to authenticated users and the row owner.

BEGIN;

ALTER TABLE IF EXISTS public.competitor_top_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.ig_auto_responders ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.ig_dm_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.inspiration_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.inspiration_ideas ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.trend_keywords ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.trend_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.trend_snapshots ENABLE ROW LEVEL SECURITY;

-- Service-only lock table: grants already deny anon/authenticated access, and
-- service_role bypasses RLS. Enabling RLS here makes that intent explicit.
ALTER TABLE IF EXISTS public.publish_locks ENABLE ROW LEVEL SECURITY;

-- Keep legacy competitor rows visible if a previous backfill left user_id null.
-- Clean branch replay can still have the early UUID shape for
-- competitor_top_posts.user_id/competitor_id here, while competitors is TEXT.
DO $$
DECLARE
  user_id_type TEXT;
BEGIN
  SELECT data_type INTO user_id_type
  FROM information_schema.columns
  WHERE table_schema = 'public'
    AND table_name = 'competitor_top_posts'
    AND column_name = 'user_id';

  IF user_id_type = 'uuid' THEN
    UPDATE public.competitor_top_posts ctp
    SET user_id = c.user_id::uuid
    FROM public.competitors c
    WHERE ctp.competitor_id::text = c.id
      AND ctp.user_id IS NULL
      AND c.user_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';
  ELSIF user_id_type IS NOT NULL THEN
    UPDATE public.competitor_top_posts ctp
    SET user_id = c.user_id
    FROM public.competitors c
    WHERE ctp.competitor_id::text = c.id
      AND ctp.user_id IS NULL;
  END IF;
END $$;

DROP POLICY IF EXISTS "Users can view competitor top posts" ON public.competitor_top_posts;
DROP POLICY IF EXISTS "Users can insert competitor top posts" ON public.competitor_top_posts;
DROP POLICY IF EXISTS "Users can update competitor top posts" ON public.competitor_top_posts;
DROP POLICY IF EXISTS "Users can delete competitor top posts" ON public.competitor_top_posts;
DROP POLICY IF EXISTS "rls_competitor_top_posts_owner_all" ON public.competitor_top_posts;

CREATE POLICY "rls_competitor_top_posts_owner_all"
  ON public.competitor_top_posts
  FOR ALL
  TO authenticated
  USING (
    user_id::text = (SELECT auth.uid())::text
    OR EXISTS (
      SELECT 1
      FROM public.competitors c
      WHERE c.id = competitor_top_posts.competitor_id::text
        AND c.user_id::text = (SELECT auth.uid())::text
    )
  )
  WITH CHECK (
    user_id::text = (SELECT auth.uid())::text
    OR EXISTS (
      SELECT 1
      FROM public.competitors c
      WHERE c.id = competitor_top_posts.competitor_id::text
        AND c.user_id::text = (SELECT auth.uid())::text
    )
  );

DROP POLICY IF EXISTS "Users can view their own auto-responders" ON public.ig_auto_responders;
DROP POLICY IF EXISTS "Users can insert their own auto-responders" ON public.ig_auto_responders;
DROP POLICY IF EXISTS "Users can update their own auto-responders" ON public.ig_auto_responders;
DROP POLICY IF EXISTS "Users can delete their own auto-responders" ON public.ig_auto_responders;
DROP POLICY IF EXISTS "rls_user_ig_auto_responders" ON public.ig_auto_responders;
DROP POLICY IF EXISTS "rls_ig_auto_responders_owner_all" ON public.ig_auto_responders;

CREATE POLICY "rls_ig_auto_responders_owner_all"
  ON public.ig_auto_responders
  FOR ALL
  TO authenticated
  USING (user_id::text = (SELECT auth.uid())::text)
  WITH CHECK (user_id::text = (SELECT auth.uid())::text);

DROP POLICY IF EXISTS "Users can view their own DM templates" ON public.ig_dm_templates;
DROP POLICY IF EXISTS "Users can insert their own DM templates" ON public.ig_dm_templates;
DROP POLICY IF EXISTS "Users can update their own DM templates" ON public.ig_dm_templates;
DROP POLICY IF EXISTS "Users can delete their own DM templates" ON public.ig_dm_templates;
DROP POLICY IF EXISTS "rls_user_ig_dm_templates" ON public.ig_dm_templates;
DROP POLICY IF EXISTS "rls_ig_dm_templates_owner_all" ON public.ig_dm_templates;

CREATE POLICY "rls_ig_dm_templates_owner_all"
  ON public.ig_dm_templates
  FOR ALL
  TO authenticated
  USING (user_id::text = (SELECT auth.uid())::text)
  WITH CHECK (user_id::text = (SELECT auth.uid())::text);

DROP POLICY IF EXISTS "Users can manage own inspiration config" ON public.inspiration_config;
DROP POLICY IF EXISTS "rls_inspiration_config_owner_all" ON public.inspiration_config;

CREATE POLICY "rls_inspiration_config_owner_all"
  ON public.inspiration_config
  FOR ALL
  TO authenticated
  USING (user_id::text = (SELECT auth.uid())::text)
  WITH CHECK (user_id::text = (SELECT auth.uid())::text);

DROP POLICY IF EXISTS "Users can manage own inspiration ideas" ON public.inspiration_ideas;
DROP POLICY IF EXISTS "Users manage own inspiration ideas" ON public.inspiration_ideas;
DROP POLICY IF EXISTS "rls_user_inspiration_ideas" ON public.inspiration_ideas;
DROP POLICY IF EXISTS "rls_inspiration_ideas_owner_all" ON public.inspiration_ideas;

CREATE POLICY "rls_inspiration_ideas_owner_all"
  ON public.inspiration_ideas
  FOR ALL
  TO authenticated
  USING (
    user_id::text = (SELECT auth.uid())::text
    AND (
      workspace_id IS NULL
      OR EXISTS (
        SELECT 1
        FROM public.workspaces w
        WHERE w.id::text = inspiration_ideas.workspace_id::text
          AND (
            w.owner_id::text = (SELECT auth.uid())::text
            OR public.is_workspace_member(w.id::text, (SELECT auth.uid())::text)
          )
      )
    )
  )
  WITH CHECK (
    user_id::text = (SELECT auth.uid())::text
    AND (
      workspace_id IS NULL
      OR EXISTS (
        SELECT 1
        FROM public.workspaces w
        WHERE w.id::text = inspiration_ideas.workspace_id::text
          AND (
            w.owner_id::text = (SELECT auth.uid())::text
            OR public.is_workspace_member(w.id::text, (SELECT auth.uid())::text)
          )
      )
    )
  );

DROP POLICY IF EXISTS "Users can manage own trend keywords" ON public.trend_keywords;
DROP POLICY IF EXISTS "rls_trend_keywords_owner_all" ON public.trend_keywords;

CREATE POLICY "rls_trend_keywords_owner_all"
  ON public.trend_keywords
  FOR ALL
  TO authenticated
  USING (user_id::text = (SELECT auth.uid())::text)
  WITH CHECK (user_id::text = (SELECT auth.uid())::text);

DROP POLICY IF EXISTS "Users can manage own trend posts" ON public.trend_posts;
DROP POLICY IF EXISTS "rls_trend_posts_owner_all" ON public.trend_posts;

CREATE POLICY "rls_trend_posts_owner_all"
  ON public.trend_posts
  FOR ALL
  TO authenticated
  USING (user_id::text = (SELECT auth.uid())::text)
  WITH CHECK (user_id::text = (SELECT auth.uid())::text);

DROP POLICY IF EXISTS "Users can manage own trend snapshots" ON public.trend_snapshots;
DROP POLICY IF EXISTS "rls_trend_snapshots_owner_all" ON public.trend_snapshots;

CREATE POLICY "rls_trend_snapshots_owner_all"
  ON public.trend_snapshots
  FOR ALL
  TO authenticated
  USING (user_id::text = (SELECT auth.uid())::text)
  WITH CHECK (user_id::text = (SELECT auth.uid())::text);

COMMIT;
