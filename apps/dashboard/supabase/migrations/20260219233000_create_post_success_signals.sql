CREATE TABLE IF NOT EXISTS post_success_signals (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  post_id text NOT NULL,
  signal text NOT NULL CHECK (signal IN ('great_media', 'trending_topic', 'perfect_timing', 'strong_hook', 'got_lucky')),
  created_at timestamptz DEFAULT now()
);
ALTER TABLE post_success_signals ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users own their signals" ON post_success_signals FOR ALL USING (user_id = auth.uid());
CREATE INDEX IF NOT EXISTS idx_post_success_signals_user ON post_success_signals(user_id, post_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_post_success_signals_unique ON post_success_signals(user_id, post_id);
