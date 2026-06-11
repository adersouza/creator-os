-- Restore service_role policy on sync_jobs that was dropped during UUID→TEXT migration
-- The service_role key bypasses RLS, so this is defense-in-depth only
CREATE POLICY "Service role can manage sync jobs"
  ON sync_jobs FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);
