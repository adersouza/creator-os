-- user_preferences already exists — just ensure RLS policy works
-- Check if RLS policy exists, create if not
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename = 'user_preferences' AND policyname = 'Users manage own preferences'
  ) THEN
    -- user_id might be text type, cast auth.uid() accordingly
    EXECUTE 'CREATE POLICY "Users manage own preferences" ON user_preferences FOR ALL USING (auth.uid()::text = user_id::text) WITH CHECK (auth.uid()::text = user_id::text)';
  END IF;
END $$;

-- Add power_user_score to profiles
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'profiles' AND column_name = 'power_user_score') THEN
    ALTER TABLE profiles ADD COLUMN power_user_score real DEFAULT 0;
  END IF;
END $$;

-- Add creator_archetype to profiles
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'profiles' AND column_name = 'creator_archetype') THEN
    ALTER TABLE profiles ADD COLUMN creator_archetype text;
  END IF;
END $$;

-- Create recommendation_dismissals if not exists
CREATE TABLE IF NOT EXISTS recommendation_dismissals (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  account_id uuid NOT NULL,
  recommendation_key text NOT NULL,
  dismissed_at timestamptz DEFAULT now(),
  reason text,
  UNIQUE(user_id, account_id, recommendation_key)
);

ALTER TABLE recommendation_dismissals ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename = 'recommendation_dismissals' AND policyname = 'Users manage own dismissals'
  ) THEN
    EXECUTE 'CREATE POLICY "Users manage own dismissals" ON recommendation_dismissals FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id)';
  END IF;
END $$;
