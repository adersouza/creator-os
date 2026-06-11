-- Fix UUID→TEXT type mismatches for columns referencing TEXT-typed parent tables
--
-- Core table IDs are TEXT: profiles.id, accounts.id, posts.id, workspaces.id
-- auth.users.id is UUID — child tables with user_id FK to auth.users are correctly UUID
--
-- Only fixing columns that join against public TEXT tables without auth.users FK:
--   creator_events.account_id   → accounts.id (TEXT)
--   rate_limit_tracking.account_id → accounts.id (TEXT)
--   post_reflections.post_id    → posts.id (TEXT)

-- ══════════════════════════════════════════════
-- creator_events.account_id (no FK constraint, no policy on this column)
-- ══════════════════════════════════════════════
DROP POLICY IF EXISTS "Users can view their own creator events" ON creator_events;
DROP POLICY IF EXISTS "Service role can insert creator events" ON creator_events;
DROP POLICY IF EXISTS "Service role can update creator events" ON creator_events;
ALTER TABLE creator_events ALTER COLUMN account_id TYPE text USING account_id::text;
CREATE POLICY "Users can view their own creator events" ON creator_events FOR SELECT TO authenticated USING (auth.uid() = user_id);
CREATE POLICY "Service role can insert creator events" ON creator_events FOR INSERT TO service_role WITH CHECK (true);
CREATE POLICY "Service role can update creator events" ON creator_events FOR UPDATE TO service_role USING (true);

-- ══════════════════════════════════════════════
-- rate_limit_tracking.account_id (no FK constraint)
-- ══════════════════════════════════════════════
DROP POLICY IF EXISTS "Service role rate_limit_tracking" ON rate_limit_tracking;
ALTER TABLE rate_limit_tracking ALTER COLUMN account_id TYPE text USING account_id::text;
CREATE POLICY "Service role rate_limit_tracking" ON rate_limit_tracking FOR ALL TO service_role USING (true) WITH CHECK (true);

-- ══════════════════════════════════════════════
-- post_reflections.post_id (no FK constraint)
-- ══════════════════════════════════════════════
DROP POLICY IF EXISTS "Users can insert their own reflections" ON post_reflections;
DROP POLICY IF EXISTS "Users can read their own reflections" ON post_reflections;
ALTER TABLE post_reflections ALTER COLUMN post_id TYPE text USING post_id::text;
CREATE POLICY "Users can read their own reflections" ON post_reflections FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Users can insert their own reflections" ON post_reflections FOR INSERT WITH CHECK (auth.uid() = user_id);
