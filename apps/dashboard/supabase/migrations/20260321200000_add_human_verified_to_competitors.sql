-- Feature 5: Model collapse prevention — only adapt posts from verified human accounts
ALTER TABLE public.competitors
  ADD COLUMN IF NOT EXISTS human_verified BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS verified_by TEXT;

COMMENT ON COLUMN public.competitors.human_verified IS
  'Manually verified as a real human account (not AI-generated). Only human_verified competitors are used for content adaptation.';
