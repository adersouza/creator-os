-- ============================================================================
-- RLS Fixes: Close remaining policy gaps
-- Date: 2026-02-18
-- 
-- Fixes:
--   1. notifications: add SELECT policy for users to read own notifications
--   2. post_replies: tighten overly-permissive "any authenticated user" policy
--   3. Missing indexes for RLS performance
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. notifications: Users can read their own notifications
-- ============================================================================

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'notifications') THEN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'notifications' AND policyname = 'Users read own notifications') THEN
      EXECUTE 'CREATE POLICY "Users read own notifications" ON notifications FOR SELECT USING ((SELECT auth.uid())::text = user_id)';
    END IF;
  END IF;
END
$$;

-- ============================================================================
-- 2. post_replies: Replace overly-permissive SELECT with scoped policy
-- ============================================================================

DROP POLICY IF EXISTS "Authenticated users can view replies" ON post_replies;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies 
    WHERE tablename = 'post_replies' 
    AND policyname LIKE '%own%'
  ) THEN
    EXECUTE '
      CREATE POLICY "Users access own post replies"
        ON post_replies FOR ALL
        USING (
          EXISTS (
            SELECT 1 FROM posts
            WHERE posts.id = post_replies.post_id
              AND posts.user_id = (SELECT auth.uid())::text
          )
        )';
  END IF;
END
$$;

-- ============================================================================
-- 3. Missing indexes for RLS policy performance
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_instagram_accounts_user_id
  ON instagram_accounts(user_id);

CREATE INDEX IF NOT EXISTS idx_accounts_user_id
  ON accounts(user_id);

CREATE INDEX IF NOT EXISTS idx_competitors_user_id
  ON competitors(user_id);

COMMIT;
