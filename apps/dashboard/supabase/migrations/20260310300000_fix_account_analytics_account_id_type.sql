-- Fix account_analytics.account_id type to match accounts.id (TEXT)
-- Original migration (20260218000001) declared it as UUID, but accounts.id is TEXT.
-- Must drop and recreate the RLS policy that references this column.

DROP POLICY IF EXISTS "Users access own account analytics" ON account_analytics;

ALTER TABLE account_analytics ALTER COLUMN account_id TYPE TEXT;

CREATE POLICY "Users access own account analytics" ON account_analytics
  FOR SELECT USING (
    EXISTS (
      SELECT 1 FROM accounts
      WHERE accounts.id = account_analytics.account_id
        AND accounts.user_id = (SELECT auth.uid())::text
    )
  );
