-- Referral System Enhancement: Free month rewards + trial for referred users
-- Builds on existing referral_codes & referrals tables from migrate-referrals.sql

-- Add reward tracking columns if not exist
DO $$ BEGIN
  -- Add referral_reward_months_earned to profiles (tracks free Pro months earned via referrals)
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'profiles' AND column_name = 'referral_reward_months_earned') THEN
    ALTER TABLE public.profiles ADD COLUMN referral_reward_months_earned INTEGER DEFAULT 0;
  END IF;

  -- Add referral_reward_months_used to profiles
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'profiles' AND column_name = 'referral_reward_months_used') THEN
    ALTER TABLE public.profiles ADD COLUMN referral_reward_months_used INTEGER DEFAULT 0;
  END IF;

  -- Add referral_trial_ends_at for referred users (7-day Pro trial)
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'profiles' AND column_name = 'referral_trial_ends_at') THEN
    ALTER TABLE public.profiles ADD COLUMN referral_trial_ends_at TIMESTAMPTZ;
  END IF;

  -- Add referred_by to profiles for quick lookup
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'profiles' AND column_name = 'referred_by') THEN
    ALTER TABLE public.profiles ADD COLUMN referred_by TEXT REFERENCES public.profiles(id);
  END IF;

  -- Update referral_codes reward_type check to include free_month when the
  -- table already exists. Fresh branch replay creates it in 20260218110000.
  IF to_regclass('public.referral_codes') IS NOT NULL THEN
    ALTER TABLE public.referral_codes DROP CONSTRAINT IF EXISTS referral_codes_reward_type_check;
    ALTER TABLE public.referral_codes ADD CONSTRAINT referral_codes_reward_type_check
      CHECK (reward_type IN ('extra_account', 'free_month', 'discount_pct', 'pro_month'));
  END IF;
END $$;

-- Function to grant referral rewards (called after referral is completed)
CREATE OR REPLACE FUNCTION grant_referral_reward()
RETURNS TRIGGER AS $$
DECLARE
  current_months INTEGER;
  max_months CONSTANT INTEGER := 12;
BEGIN
  IF NEW.status = 'completed' AND (OLD.status IS NULL OR OLD.status != 'completed') THEN
    -- Get current earned months for referrer
    SELECT COALESCE(referral_reward_months_earned, 0) INTO current_months
    FROM public.profiles WHERE id = NEW.referrer_id;

    -- Cap at 12 months
    IF current_months < max_months THEN
      -- Grant 1 free Pro month to referrer
      UPDATE public.profiles
      SET referral_reward_months_earned = LEAST(current_months + 1, max_months),
          updated_at = NOW()
      WHERE id = NEW.referrer_id;

      -- Mark referral as rewarded
      NEW.status := 'rewarded';
      NEW.reward_granted_at := NOW();
    END IF;

    -- Grant 7-day Pro trial to referred user
    UPDATE public.profiles
    SET referral_trial_ends_at = NOW() + INTERVAL '7 days',
        referred_by = NEW.referrer_id,
        updated_at = NOW()
    WHERE id = NEW.referred_id
      AND referral_trial_ends_at IS NULL;
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DO $$
BEGIN
  IF to_regclass('public.referrals') IS NOT NULL THEN
    ALTER TABLE public.referrals ADD COLUMN IF NOT EXISTS reward_granted_at TIMESTAMPTZ;

    DROP TRIGGER IF EXISTS trg_grant_referral_reward ON public.referrals;
    CREATE TRIGGER trg_grant_referral_reward
      BEFORE INSERT OR UPDATE ON public.referrals
      FOR EACH ROW
      EXECUTE FUNCTION grant_referral_reward();

    CREATE POLICY "Service can update referrals" ON public.referrals
      FOR UPDATE USING (true) WITH CHECK (true);

    DROP POLICY IF EXISTS "Users can apply referral codes" ON public.referrals;
    CREATE POLICY "Users can apply referral codes" ON public.referrals
      FOR INSERT WITH CHECK (referred_id = auth.uid());
  END IF;
END $$;
