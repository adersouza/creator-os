CREATE TABLE IF NOT EXISTS ai_feedback (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  feature text NOT NULL,
  input_context jsonb,
  output_text text,
  rating integer CHECK (rating IN (-1, 1)),
  comment text,
  created_at timestamptz DEFAULT now()
);
ALTER TABLE ai_feedback ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users own their feedback" ON ai_feedback FOR ALL USING (user_id = auth.uid()::text);
