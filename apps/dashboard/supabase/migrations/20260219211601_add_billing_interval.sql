ALTER TABLE profiles ADD COLUMN IF NOT EXISTS billing_interval text DEFAULT 'monthly' CHECK (billing_interval IN ('monthly', 'annual'));
