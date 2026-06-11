-- Add covering indexes for 12 unindexed foreign keys.
-- Without these, DELETE/UPDATE on the parent table triggers sequential scans
-- on the child table to check for referencing rows.

CREATE INDEX IF NOT EXISTS idx_anomaly_alerts_ig_account_id
    ON anomaly_alerts (instagram_account_id);

CREATE INDEX IF NOT EXISTS idx_link_items_target_smart_link_id
    ON link_items (target_smart_link_id);

CREATE INDEX IF NOT EXISTS idx_posts_recycled_from_id
    ON posts (recycled_from_id);

CREATE INDEX IF NOT EXISTS idx_posts_rejected_by
    ON posts (rejected_by);

CREATE INDEX IF NOT EXISTS idx_referrals_referral_code_id
    ON referrals (referral_code_id);

CREATE INDEX IF NOT EXISTS idx_rss_entries_post_id
    ON rss_entries (post_id);

CREATE INDEX IF NOT EXISTS idx_rss_feeds_account_id
    ON rss_feeds (account_id);

CREATE INDEX IF NOT EXISTS idx_rss_feeds_ig_account_id
    ON rss_feeds (instagram_account_id);

CREATE INDEX IF NOT EXISTS idx_smart_link_conversions_click_id
    ON smart_link_conversions (click_id);

CREATE INDEX IF NOT EXISTS idx_trend_forecasts_account_id
    ON trend_forecasts (account_id);

CREATE INDEX IF NOT EXISTS idx_unified_links_user_id
    ON unified_links (user_id);

CREATE INDEX IF NOT EXISTS idx_unified_links_workspace_id
    ON unified_links (workspace_id);
