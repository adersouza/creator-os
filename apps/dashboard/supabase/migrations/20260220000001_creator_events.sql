-- Creator Events table for tracking major events in a user's journey
CREATE TABLE IF NOT EXISTS creator_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  account_id uuid NOT NULL,
  event_type text NOT NULL CHECK (event_type IN ('viral_post', 'follower_spike', 'content_shift', 'engagement_drop', 'quick_win_milestone', 'archetype_change')),
  event_date timestamptz NOT NULL DEFAULT now(),
  description text NOT NULL,
  metrics_snapshot jsonb DEFAULT '{}',
  impact_duration_days integer,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_creator_events_user_account ON creator_events(user_id, account_id);
CREATE INDEX IF NOT EXISTS idx_creator_events_type_date ON creator_events(account_id, event_type, event_date DESC);

-- RLS
ALTER TABLE creator_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view their own creator events"
  ON creator_events FOR SELECT
  TO authenticated
  USING (auth.uid() = user_id);

CREATE POLICY "Service role can insert creator events"
  ON creator_events FOR INSERT
  TO service_role
  WITH CHECK (true);

CREATE POLICY "Service role can update creator events"
  ON creator_events FOR UPDATE
  TO service_role
  USING (true);
