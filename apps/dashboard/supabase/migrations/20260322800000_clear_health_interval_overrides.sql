-- Clear all health-based interval overrides from auto_post_account_overrides.
-- The health scorer was writing wider min/max intervals for struggling/dead
-- accounts, throttling their posting. Health scoring is now reporting-only —
-- every account posts at group-default intervals regardless of health tier.

DELETE FROM auto_post_account_overrides
WHERE (overrides->>'min_interval_minutes') IS NOT NULL;
