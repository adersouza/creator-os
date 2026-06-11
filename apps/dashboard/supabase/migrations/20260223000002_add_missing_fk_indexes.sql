-- ============================================================================
-- Add missing indexes on foreign key columns
--
-- Foreign keys without covering indexes cause full sequential scans on the
-- child table when the parent row is deleted (CASCADE). These 4 FK columns
-- were flagged by the Supabase linter.
-- ============================================================================

-- anomaly_alerts.instagram_account_id → instagram_accounts(id)
CREATE INDEX IF NOT EXISTS idx_anomaly_alerts_instagram_account_id
  ON anomaly_alerts(instagram_account_id);

-- posts.rejected_by → profiles(id)
CREATE INDEX IF NOT EXISTS idx_posts_rejected_by
  ON posts(rejected_by);

-- referrals.referral_code_id → referral_codes(id)
CREATE INDEX IF NOT EXISTS idx_referrals_referral_code_id
  ON referrals(referral_code_id);

-- smart_link_conversions.click_id → smart_link_clicks(id)
CREATE INDEX IF NOT EXISTS idx_smart_link_conversions_click_id
  ON smart_link_conversions(click_id);
