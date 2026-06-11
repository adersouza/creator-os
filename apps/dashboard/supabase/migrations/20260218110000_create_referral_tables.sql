-- Referral system tables
-- referral_codes: stores user-generated referral codes
-- referrals: tracks who referred whom

CREATE TABLE IF NOT EXISTS public.referral_codes (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  code text NOT NULL UNIQUE,
  reward_type text NOT NULL DEFAULT 'extra_account',
  reward_value integer NOT NULL DEFAULT 1,
  max_uses integer NOT NULL DEFAULT 0, -- 0 = unlimited
  uses integer NOT NULL DEFAULT 0,
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.referrals (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  referrer_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  referred_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  referral_code_id uuid REFERENCES public.referral_codes(id) ON DELETE SET NULL,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'rewarded', 'expired')),
  reward_granted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(referred_id) -- each user can only be referred once
);

ALTER TABLE public.referral_codes DROP CONSTRAINT IF EXISTS referral_codes_reward_type_check;
ALTER TABLE public.referral_codes ADD CONSTRAINT referral_codes_reward_type_check
  CHECK (reward_type IN ('extra_account', 'free_month', 'discount_pct', 'pro_month'));

-- Add referral reward columns to profiles if not exist
DO $$ BEGIN
  ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS referral_reward_months_earned integer DEFAULT 0;
  ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS referral_reward_months_used integer DEFAULT 0;
  ALTER TABLE public.profiles ADD COLUMN IF NOT EXISTS referral_trial_ends_at timestamptz;
EXCEPTION WHEN others THEN NULL;
END $$;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_referral_codes_user_id ON public.referral_codes(user_id);
CREATE INDEX IF NOT EXISTS idx_referral_codes_code ON public.referral_codes(code);
CREATE INDEX IF NOT EXISTS idx_referrals_referrer_id ON public.referrals(referrer_id);
CREATE INDEX IF NOT EXISTS idx_referrals_referred_id ON public.referrals(referred_id);

-- RLS
ALTER TABLE public.referral_codes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.referrals ENABLE ROW LEVEL SECURITY;

-- Users can read their own codes
CREATE POLICY "Users can read own referral codes" ON public.referral_codes
  FOR SELECT USING (auth.uid() = user_id);

-- Users can insert their own codes
CREATE POLICY "Users can create own referral codes" ON public.referral_codes
  FOR INSERT WITH CHECK (auth.uid() = user_id);

-- Users can update their own codes
CREATE POLICY "Users can update own referral codes" ON public.referral_codes
  FOR UPDATE USING (auth.uid() = user_id);

-- Anyone can validate a code (read by code)
CREATE POLICY "Anyone can validate referral codes" ON public.referral_codes
  FOR SELECT USING (is_active = true);

-- Users can read referrals they're part of
CREATE POLICY "Users can read own referrals" ON public.referrals
  FOR SELECT USING (auth.uid() = referrer_id OR auth.uid() = referred_id);

-- Users can create referrals where they are the referred
CREATE POLICY "Users can create referrals as referred" ON public.referrals
  FOR INSERT WITH CHECK (auth.uid() = referred_id);

DROP TRIGGER IF EXISTS trg_grant_referral_reward ON public.referrals;
CREATE TRIGGER trg_grant_referral_reward
  BEFORE INSERT OR UPDATE ON public.referrals
  FOR EACH ROW
  EXECUTE FUNCTION grant_referral_reward();

CREATE POLICY "Service can update referrals" ON public.referrals
  FOR UPDATE USING (true) WITH CHECK (true);

-- Helper function to generate referral codes
CREATE OR REPLACE FUNCTION public.generate_referral_code(username text)
RETURNS text
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
  prefix text;
  suffix text;
  result text;
  attempts integer := 0;
BEGIN
  prefix := upper(left(username, 4));
  LOOP
    suffix := lpad(floor(random() * 10000)::text, 4, '0');
    result := prefix || suffix;
    EXIT WHEN NOT EXISTS (SELECT 1 FROM referral_codes WHERE code = result);
    attempts := attempts + 1;
    EXIT WHEN attempts > 10;
  END LOOP;
  RETURN result;
END;
$$;
