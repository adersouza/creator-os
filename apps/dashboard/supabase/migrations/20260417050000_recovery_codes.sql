-- TOTP backup codes — Supabase native MFA does not ship these, so we store
-- hashed recovery codes alongside the factor. Client never talks to this
-- table directly; everything goes through /api/auth/mfa-backup which uses
-- the service role to insert on generate and atomically mark used on verify.

CREATE TABLE IF NOT EXISTS public.recovery_codes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  code_hash TEXT NOT NULL,
  used_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Fast "unused codes for this user" lookup — also how the backend count check
-- works for the Settings UI badge.
CREATE INDEX IF NOT EXISTS recovery_codes_user_unused_idx
  ON public.recovery_codes (user_id)
  WHERE used_at IS NULL;

ALTER TABLE public.recovery_codes ENABLE ROW LEVEL SECURITY;
-- No policies. Service role bypasses RLS; authenticated users see zero rows.
-- Code hashes are sensitive even at rest — no reason to expose them client-side.
