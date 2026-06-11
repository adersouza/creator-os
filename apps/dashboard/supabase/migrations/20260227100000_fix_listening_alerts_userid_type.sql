-- C3: Fix listening_alerts.user_id type from UUID to TEXT
-- The column was created as UUID REFERENCES auth.users(id) but all API queries
-- use user.id as TEXT (from withAuth middleware). This causes silent query failures.
-- Must drop ALL policies on BOTH tables before ALTER TYPE.

-- Drop all policies on listening_results (references listening_alerts.user_id)
DROP POLICY IF EXISTS "Users can view own listening results" ON listening_results;
DROP POLICY IF EXISTS "Users can insert own listening results" ON listening_results;
DROP POLICY IF EXISTS "Users can manage own listening results" ON listening_results;
DROP POLICY IF EXISTS "Users access listening results" ON listening_results;

-- Drop all policies on listening_alerts
DROP POLICY IF EXISTS "Users access listening alerts" ON listening_alerts;
DROP POLICY IF EXISTS "Users can manage own listening alerts" ON listening_alerts;
DROP POLICY IF EXISTS "Users can view own listening alerts" ON listening_alerts;
DROP POLICY IF EXISTS "Users can insert own listening alerts" ON listening_alerts;
DROP POLICY IF EXISTS "Users can update own listening alerts" ON listening_alerts;
DROP POLICY IF EXISTS "Users can delete own listening alerts" ON listening_alerts;

-- Drop existing FK constraint
ALTER TABLE listening_alerts DROP CONSTRAINT IF EXISTS listening_alerts_user_id_fkey;

-- Convert column type from UUID to TEXT
ALTER TABLE listening_alerts ALTER COLUMN user_id TYPE TEXT USING user_id::text;

-- Re-add FK referencing profiles(id) with CASCADE (matches all other user_id columns)
ALTER TABLE listening_alerts ADD CONSTRAINT listening_alerts_user_id_fkey
  FOREIGN KEY (user_id) REFERENCES profiles(id) ON DELETE CASCADE;

-- C4: Recreate RLS policies with correct ::text cast + initplan optimization
CREATE POLICY "Users can manage own listening alerts" ON listening_alerts
  FOR ALL USING (user_id = (select auth.uid()::text));

CREATE POLICY "Users can view own listening results" ON listening_results
  FOR SELECT USING (
    alert_id IN (
      SELECT id FROM listening_alerts
      WHERE user_id = (select auth.uid()::text)
    )
  );

-- Add index for the FK if not exists
CREATE INDEX IF NOT EXISTS idx_listening_alerts_user_id ON listening_alerts(user_id);
