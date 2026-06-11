-- Metrics audit gaps (2026-04-23)
-- Three additions wired in one migration:
--   1. threads_link_click_breakdown — persist per-URL click counts
--      (we already sum link_total_values into account_analytics.total_clicks
--      and discard the URLs).
--   2. audience_demographics.audience_type — discriminator for the existing
--      table so we can store engaged_audience_demographics alongside the
--      follower demographics.
--   3. posts.ig_post_profile_activity — JSONB breakdown of profile_activity
--      action_types (profile_visits / follows / bio_link_taps / etc.) for
--      both feed posts and stories. JSONB keeps us flexible as Meta adds
--      new action_type values.

-- 1. Per-link click breakdown for Threads ----------------------------------
CREATE TABLE IF NOT EXISTS threads_link_click_breakdown (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  account_id text NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  fetched_date date NOT NULL DEFAULT CURRENT_DATE,
  link_url text NOT NULL,
  clicks integer NOT NULL DEFAULT 0,
  fetched_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_threads_link_clicks_unique
  ON threads_link_click_breakdown (account_id, fetched_date, link_url);

CREATE INDEX IF NOT EXISTS idx_threads_link_clicks_account_date
  ON threads_link_click_breakdown (account_id, fetched_date DESC);

ALTER TABLE threads_link_click_breakdown ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own threads link clicks"
  ON threads_link_click_breakdown FOR SELECT
  USING (account_id IN (SELECT id FROM accounts WHERE user_id = auth.uid()::text));

-- 2. Discriminator on existing demographics table --------------------------
ALTER TABLE audience_demographics
  ADD COLUMN IF NOT EXISTS audience_type text NOT NULL DEFAULT 'followers'
  CHECK (audience_type IN ('followers', 'engaged'));

-- Existing unique index covers (account_id, platform, breakdown_type, breakdown_value, fetched_date)
-- We need audience_type in the key so 'followers' and 'engaged' coexist for the same day.
DROP INDEX IF EXISTS idx_demographics_unique;
CREATE UNIQUE INDEX IF NOT EXISTS idx_demographics_unique
  ON audience_demographics
  (account_id, platform, audience_type, breakdown_type, breakdown_value, fetched_date);

-- 3. Profile activity breakdown on posts -----------------------------------
ALTER TABLE posts
  ADD COLUMN IF NOT EXISTS ig_post_profile_activity jsonb;

COMMENT ON COLUMN posts.ig_post_profile_activity IS
  'IG profile_activity breakdown by action_type. Shape: [{"action_type": "...", "value": n}, ...]. Populated for feed/image posts and stories; not for Reels.';
