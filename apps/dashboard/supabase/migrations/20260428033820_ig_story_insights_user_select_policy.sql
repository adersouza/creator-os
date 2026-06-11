-- ig_story_insights: add SELECT policy for authenticated users
--
-- The table previously had only a service_role policy (see
-- 20260223000000_fix_linter_warnings.sql). Authenticated browser clients
-- received zero rows on every query, which broke the dashboard's
-- StoryProfileActivityTile permanently. The tile was always rendering
-- the empty state regardless of whether the cron had ingested story
-- insights for the user's accounts.
--
-- Authentication scope: a user can read story insights only for IG
-- accounts whose `instagram_accounts.user_id` matches their auth uid.
-- Pattern matches the existing audience_demographics policy in
-- 20260222020000_user_id_uuid_to_text.sql.

BEGIN;

CREATE POLICY "Users can view own IG story insights"
  ON ig_story_insights FOR SELECT
  TO authenticated
  USING (
    ig_user_id IN (
      SELECT ig_user_id
      FROM instagram_accounts
      WHERE user_id = (SELECT auth.uid())::text
    )
  );

COMMIT;
