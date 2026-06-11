-- Migration: Add goal tracking tables
-- These tables support the Goal Tracker feature

-- User goals
CREATE TABLE IF NOT EXISTS public.user_goals (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('followers', 'engagement', 'views', 'posts')),
  target_value INTEGER NOT NULL,
  current_value INTEGER DEFAULT 0,
  deadline TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_goals_user_id ON public.user_goals(user_id);

ALTER TABLE public.user_goals ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can manage own goals" ON public.user_goals
  FOR ALL USING (auth.uid()::text = user_id);

-- Goal history snapshots for tracking progress over time
CREATE TABLE IF NOT EXISTS public.goal_history_snapshots (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  goal_id UUID NOT NULL REFERENCES public.user_goals(id) ON DELETE CASCADE,
  date TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  value INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_goal_history_user_id ON public.goal_history_snapshots(user_id);
CREATE INDEX IF NOT EXISTS idx_goal_history_goal_id ON public.goal_history_snapshots(goal_id);
CREATE INDEX IF NOT EXISTS idx_goal_history_date ON public.goal_history_snapshots(date DESC);

ALTER TABLE public.goal_history_snapshots ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can manage own goal history" ON public.goal_history_snapshots
  FOR ALL USING (auth.uid()::text = user_id);

SELECT 'Goal tables created successfully' AS status;
