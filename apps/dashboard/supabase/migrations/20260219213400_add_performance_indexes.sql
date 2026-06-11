-- Performance indexes for common query patterns

CREATE INDEX IF NOT EXISTS idx_posts_account_published
  ON posts(account_id, published_at DESC);

CREATE INDEX IF NOT EXISTS idx_analytics_account_date
  ON account_analytics(account_id, date DESC);

CREATE INDEX IF NOT EXISTS idx_posts_account_type_engagement
  ON posts(account_id, media_type, engagement_rate DESC);

CREATE INDEX IF NOT EXISTS idx_feature_usage_user_feature
  ON feature_usage(user_id, feature_name, used_at DESC);

CREATE INDEX IF NOT EXISTS idx_anomaly_alerts_user_active
  ON anomaly_alerts(user_id, dismissed_at) WHERE dismissed_at IS NULL;
