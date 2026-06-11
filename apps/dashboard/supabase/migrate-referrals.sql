-- Referral System
CREATE TABLE public.referral_codes (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  code TEXT NOT NULL UNIQUE,
  uses INTEGER DEFAULT 0,
  max_uses INTEGER DEFAULT 0, -- 0 = unlimited
  reward_type TEXT DEFAULT 'extra_account' CHECK (reward_type IN ('extra_account', 'free_month', 'discount_pct')),
  reward_value INTEGER DEFAULT 1, -- 1 extra account, 1 free month, or 10% off
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  expires_at TIMESTAMPTZ
);

CREATE TABLE public.referrals (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  referrer_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  referred_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  referral_code_id UUID NOT NULL REFERENCES public.referral_codes(id) ON DELETE CASCADE,
  status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'completed', 'rewarded')),
  reward_granted_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(referred_id) -- each user can only be referred once
);

CREATE INDEX idx_referral_codes_user_id ON public.referral_codes(user_id);
CREATE INDEX idx_referral_codes_code ON public.referral_codes(code);
CREATE INDEX idx_referrals_referrer_id ON public.referrals(referrer_id);

-- RLS
ALTER TABLE public.referral_codes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.referrals ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own referral codes" ON public.referral_codes
  FOR SELECT USING (user_id = auth.uid());

CREATE POLICY "Users can create own referral codes" ON public.referral_codes
  FOR INSERT WITH CHECK (user_id = auth.uid());

CREATE POLICY "Users can view own referrals" ON public.referrals
  FOR SELECT USING (referrer_id = auth.uid() OR referred_id = auth.uid());

-- Function to generate unique referral code
CREATE OR REPLACE FUNCTION generate_referral_code(username TEXT)
RETURNS TEXT AS $$
DECLARE
  base_code TEXT;
  final_code TEXT;
  counter INTEGER := 0;
BEGIN
  base_code := UPPER(LEFT(REGEXP_REPLACE(username, '[^a-zA-Z0-9]', '', 'g'), 6));
  IF LENGTH(base_code) < 3 THEN
    base_code := 'REF';
  END IF;
  final_code := base_code || LPAD(FLOOR(RANDOM() * 1000)::TEXT, 3, '0');
  WHILE EXISTS (SELECT 1 FROM public.referral_codes WHERE code = final_code) LOOP
    counter := counter + 1;
    final_code := base_code || LPAD((FLOOR(RANDOM() * 10000))::TEXT, 4, '0');
    IF counter > 10 THEN
      final_code := base_code || LPAD((FLOOR(RANDOM() * 100000))::TEXT, 5, '0');
    END IF;
  END LOOP;
  RETURN final_code;
END;
$$ LANGUAGE plpgsql;
