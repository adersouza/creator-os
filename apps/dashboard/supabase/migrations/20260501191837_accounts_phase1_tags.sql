ALTER TABLE public.accounts
  ADD COLUMN IF NOT EXISTS tags TEXT[] DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_accounts_tags
  ON public.accounts USING GIN(tags);
