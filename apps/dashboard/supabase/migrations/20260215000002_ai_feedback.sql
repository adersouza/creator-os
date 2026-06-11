-- AI Feedback tracking — learn from which AI suggestions users pick
CREATE TABLE IF NOT EXISTS ai_feedback (
  id TEXT DEFAULT gen_random_uuid()::TEXT PRIMARY KEY,
  workspace_id TEXT,
  user_id TEXT,
  feature TEXT NOT NULL, -- 'reply_suggestion' | 'post_idea' | 'content_variation' | 'dm_response' | 'hashtag_set' | 'caption'
  suggestion_index INT, -- which of the N suggestions was picked (0-indexed)
  suggestion_content TEXT,
  was_edited BOOLEAN DEFAULT false,
  was_used BOOLEAN DEFAULT true,
  context JSONB, -- metadata about the generation (tone, topic, etc.)
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ai_feedback_workspace ON ai_feedback(workspace_id);
CREATE INDEX IF NOT EXISTS idx_ai_feedback_feature ON ai_feedback(feature);
CREATE INDEX IF NOT EXISTS idx_ai_feedback_user ON ai_feedback(user_id);

-- RLS
ALTER TABLE ai_feedback ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access on ai_feedback"
  ON ai_feedback
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);
