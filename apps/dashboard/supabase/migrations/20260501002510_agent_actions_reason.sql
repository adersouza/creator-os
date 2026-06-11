ALTER TABLE public.agent_actions
  ADD COLUMN IF NOT EXISTS reason TEXT;
