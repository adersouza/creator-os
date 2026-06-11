-- ============================================
-- CUSTOM DOMAINS for link-in-bio pages
-- ============================================

-- Add custom domain column to link_pages
ALTER TABLE public.link_pages
  ADD COLUMN IF NOT EXISTS custom_domain TEXT UNIQUE,
  ADD COLUMN IF NOT EXISTS domain_verified BOOLEAN DEFAULT false,
  ADD COLUMN IF NOT EXISTS domain_verified_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_link_pages_custom_domain
  ON public.link_pages(custom_domain) WHERE custom_domain IS NOT NULL;

-- Domain verification records
CREATE TABLE IF NOT EXISTS public.domain_verifications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  page_id UUID NOT NULL REFERENCES public.link_pages(id) ON DELETE CASCADE,
  domain TEXT NOT NULL,
  verification_token TEXT NOT NULL,
  cname_target TEXT NOT NULL DEFAULT 'cname.juno33.com',
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'verified', 'failed', 'expired')),
  last_checked_at TIMESTAMPTZ,
  verified_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  expires_at TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '7 days'),
  UNIQUE(domain)
);

CREATE INDEX IF NOT EXISTS idx_domain_verifications_user
  ON public.domain_verifications(user_id);
CREATE INDEX IF NOT EXISTS idx_domain_verifications_domain
  ON public.domain_verifications(domain);
CREATE INDEX IF NOT EXISTS idx_domain_verifications_pending
  ON public.domain_verifications(status) WHERE status = 'pending';

ALTER TABLE public.domain_verifications ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can manage own domain verifications"
  ON public.domain_verifications FOR ALL
  USING (auth.uid()::text = user_id);
