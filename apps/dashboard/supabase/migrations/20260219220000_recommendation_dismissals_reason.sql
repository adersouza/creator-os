-- Add reason and resurface_at columns to recommendation_dismissals
-- (Create table if it doesn't exist)

CREATE TABLE IF NOT EXISTS recommendation_dismissals (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  account_id text NOT NULL,
  rec_id text NOT NULL,
  category text,
  dismissed_at timestamptz DEFAULT now(),
  reason text, -- 'already_doing' | 'not_relevant' | 'will_try_later'
  resurface_at timestamptz,
  auto_solved boolean DEFAULT false,
  UNIQUE(user_id, account_id, rec_id)
);

-- Add columns if table already existed without them
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='recommendation_dismissals' AND column_name='reason') THEN
    ALTER TABLE recommendation_dismissals ADD COLUMN reason text;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='recommendation_dismissals' AND column_name='resurface_at') THEN
    ALTER TABLE recommendation_dismissals ADD COLUMN resurface_at timestamptz;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='recommendation_dismissals' AND column_name='auto_solved') THEN
    ALTER TABLE recommendation_dismissals ADD COLUMN auto_solved boolean DEFAULT false;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='recommendation_dismissals' AND column_name='category') THEN
    ALTER TABLE recommendation_dismissals ADD COLUMN category text;
  END IF;
END $$;

-- RLS
ALTER TABLE recommendation_dismissals ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  CREATE POLICY "Users can manage own dismissals"
    ON recommendation_dismissals FOR ALL USING (user_id = auth.uid());
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Index for resurface queries
CREATE INDEX IF NOT EXISTS idx_rec_dismissals_resurface
  ON recommendation_dismissals(user_id, resurface_at)
  WHERE resurface_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_rec_dismissals_category_reason
  ON recommendation_dismissals(user_id, category, reason);
