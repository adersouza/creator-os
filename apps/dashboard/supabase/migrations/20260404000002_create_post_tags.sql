-- Post tagging system for campaign/content pillar analytics
-- Junction table: many-to-many posts ↔ tags

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

CREATE POLICY "Users manage own post tags"
  ON post_tags FOR ALL
  USING (auth.uid()::text = user_id)
  WITH CHECK (auth.uid()::text = user_id);

CREATE INDEX idx_post_tags_post ON post_tags(post_id);
CREATE INDEX idx_post_tags_user_tag ON post_tags(user_id, tag_name);
CREATE INDEX idx_post_tags_user ON post_tags(user_id);

-- User tag palette: saved tag definitions with colors
CREATE TABLE IF NOT EXISTS user_tag_palette (
  id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
  user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  tag_name TEXT NOT NULL CHECK (char_length(tag_name) <= 50),
  tag_color TEXT DEFAULT '#38bdf8',
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (user_id, tag_name)
);

ALTER TABLE user_tag_palette ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users manage own tag palette"
  ON user_tag_palette FOR ALL
  USING (auth.uid()::text = user_id)
  WITH CHECK (auth.uid()::text = user_id);
