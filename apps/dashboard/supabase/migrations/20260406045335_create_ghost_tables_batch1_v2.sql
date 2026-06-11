-- Reconstructed from schema_migrations on prod (remote-only).
-- version: 20260406045335
-- applied-by: create_ghost_tables_batch1_v2 migration row


-- =============================================================================
-- Create 8 ghost tables that code references but don't exist in live DB
-- =============================================================================

-- 1. chart_annotations
CREATE TABLE IF NOT EXISTS chart_annotations (
  id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  annotation_date DATE NOT NULL,
  label TEXT NOT NULL CHECK (char_length(label) <= 200),
  color TEXT DEFAULT '#38bdf8',
  annotation_type TEXT DEFAULT 'line' CHECK (annotation_type IN ('line', 'area')),
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (user_id, account_id, annotation_date, label)
);
ALTER TABLE chart_annotations ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Users manage own annotations" ON chart_annotations;
CREATE POLICY "Users manage own annotations" ON chart_annotations FOR ALL
  USING (auth.uid()::text = user_id) WITH CHECK (auth.uid()::text = user_id);
CREATE INDEX IF NOT EXISTS idx_chart_annotations_account ON chart_annotations(account_id, annotation_date);

-- 2. post_tags
CREATE TABLE IF NOT EXISTS post_tags (
  id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  tag_name TEXT NOT NULL CHECK (char_length(tag_name) <= 50),
  tag_color TEXT DEFAULT '#38bdf8' CHECK (char_length(tag_color) <= 20),
  user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (post_id, tag_name, user_id)
);
ALTER TABLE post_tags ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Users manage own post tags" ON post_tags;
CREATE POLICY "Users manage own post tags" ON post_tags FOR ALL
  USING (auth.uid()::text = user_id) WITH CHECK (auth.uid()::text = user_id);
CREATE INDEX IF NOT EXISTS idx_post_tags_post ON post_tags(post_id);
CREATE INDEX IF NOT EXISTS idx_post_tags_user_tag ON post_tags(user_id, tag_name);
CREATE INDEX IF NOT EXISTS idx_post_tags_user ON post_tags(user_id);

-- 3. user_tag_palette
CREATE TABLE IF NOT EXISTS user_tag_palette (
  id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  tag_name TEXT NOT NULL CHECK (char_length(tag_name) <= 50),
  tag_color TEXT DEFAULT '#38bdf8',
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (user_id, tag_name)
);
ALTER TABLE user_tag_palette ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Users manage own tag palette" ON user_tag_palette;
CREATE POLICY "Users manage own tag palette" ON user_tag_palette FOR ALL
  USING (auth.uid()::text = user_id) WITH CHECK (auth.uid()::text = user_id);

-- 4. report_schedules
CREATE TABLE IF NOT EXISTS report_schedules (
  id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  account_id TEXT NOT NULL,
  schedule_type TEXT NOT NULL CHECK (schedule_type IN ('weekly', 'monthly')),
  report_type TEXT NOT NULL CHECK (report_type IN ('weekly', 'monthly', 'custom')),
  day_of_week INT CHECK (day_of_week BETWEEN 0 AND 6),
  day_of_month INT CHECK (day_of_month BETWEEN 1 AND 28),
  recipient_emails TEXT[] DEFAULT '{}',
  include_recommendations BOOLEAN DEFAULT true,
  client_name TEXT,
  platform TEXT DEFAULT 'threads',
  is_active BOOLEAN DEFAULT true,
  last_sent_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE report_schedules ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Users manage own report schedules" ON report_schedules;
CREATE POLICY "Users manage own report schedules" ON report_schedules FOR ALL
  USING (auth.uid()::text = user_id) WITH CHECK (auth.uid()::text = user_id);
CREATE INDEX IF NOT EXISTS idx_report_schedules_user ON report_schedules(user_id, is_active);

-- 5. shared_reports
CREATE TABLE IF NOT EXISTS shared_reports (
  id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  report_data JSONB NOT NULL,
  share_token TEXT UNIQUE NOT NULL DEFAULT gen_random_uuid()::text,
  expires_at TIMESTAMPTZ NOT NULL,
  view_count INT DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE shared_reports ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Users manage own shared reports" ON shared_reports;
CREATE POLICY "Users manage own shared reports" ON shared_reports FOR ALL
  USING (auth.uid()::text = user_id) WITH CHECK (auth.uid()::text = user_id);
DROP POLICY IF EXISTS "Public read by share token" ON shared_reports;
CREATE POLICY "Public read by share token" ON shared_reports FOR SELECT USING (true);
CREATE INDEX IF NOT EXISTS idx_shared_reports_token ON shared_reports(share_token);

-- 6. share_of_voice_history
CREATE TABLE IF NOT EXISTS share_of_voice_history (
  id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  account_id TEXT NOT NULL,
  competitor_id TEXT,
  date DATE NOT NULL,
  engagement_share NUMERIC(5,2),
  follower_share NUMERIC(5,2),
  content_volume_share NUMERIC(5,2),
  recorded_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE share_of_voice_history ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Users access own SoV history" ON share_of_voice_history;
CREATE POLICY "Users access own SoV history" ON share_of_voice_history FOR ALL
  USING (auth.uid()::text = user_id) WITH CHECK (auth.uid()::text = user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sov_history_user_account_date ON share_of_voice_history(user_id, account_id, date);
CREATE INDEX IF NOT EXISTS idx_sov_history_account_date ON share_of_voice_history(account_id, date);

-- 7. inbox_dm_messages
CREATE TABLE IF NOT EXISTS inbox_dm_messages (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  ig_account_id UUID NOT NULL REFERENCES instagram_accounts(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  sender_id TEXT,
  sender_username TEXT,
  message_text TEXT,
  attachment_type TEXT,
  attachment_url TEXT,
  is_echo BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL,
  synced_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE inbox_dm_messages ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Users can read own DM messages" ON inbox_dm_messages;
CREATE POLICY "Users can read own DM messages" ON inbox_dm_messages FOR SELECT
  USING (auth.uid()::text = user_id);
CREATE INDEX IF NOT EXISTS idx_dm_msgs_convo ON inbox_dm_messages(conversation_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_dm_msgs_user ON inbox_dm_messages(user_id, ig_account_id);

-- 8. shield_log (page_id is UUID to match link_pages.id)
CREATE TABLE IF NOT EXISTS shield_log (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  page_id UUID NOT NULL REFERENCES link_pages(id) ON DELETE CASCADE,
  bot_type TEXT NOT NULL,
  shield_mode VARCHAR(10) NOT NULL,
  country TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE shield_log ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS shield_log_select ON shield_log;
CREATE POLICY shield_log_select ON shield_log FOR SELECT USING (
  page_id IN (SELECT id FROM link_pages WHERE user_id = auth.uid()::text)
);
CREATE INDEX IF NOT EXISTS idx_shield_log_page_id ON shield_log(page_id);
