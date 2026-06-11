-- Backfilled from DB migration history
CREATE OR REPLACE FUNCTION get_aggregated_analytics(
  p_user_id TEXT, p_days INTEGER DEFAULT 90, p_platform TEXT DEFAULT 'threads', p_account_ids TEXT[] DEFAULT NULL
) RETURNS TABLE (
  date DATE, followers_count BIGINT, total_views BIGINT, total_likes BIGINT, total_replies BIGINT,
  total_reposts BIGINT, total_quotes BIGINT, total_shares BIGINT, total_clicks BIGINT, engagement_rate NUMERIC
) AS $$
BEGIN
  IF p_platform = 'instagram' THEN
    RETURN QUERY SELECT aa.date,
      SUM(COALESCE(aa.followers_count,0))::BIGINT, SUM(COALESCE(aa.total_views,0))::BIGINT,
      SUM(COALESCE(aa.total_likes,0))::BIGINT, SUM(COALESCE(aa.total_replies,0))::BIGINT,
      SUM(COALESCE(aa.total_reposts,0))::BIGINT, SUM(COALESCE(aa.total_quotes,0))::BIGINT,
      SUM(COALESCE(aa.total_shares,0))::BIGINT, SUM(COALESCE(aa.total_clicks,0))::BIGINT,
      CASE WHEN SUM(COALESCE(aa.total_views,0)) > 0 THEN
        (SUM(COALESCE(aa.total_likes,0))+SUM(COALESCE(aa.total_replies,0))+SUM(COALESCE(aa.total_reposts,0))+SUM(COALESCE(aa.total_shares,0)))::NUMERIC / SUM(COALESCE(aa.total_views,0))
        ELSE 0 END
    FROM account_analytics aa JOIN instagram_accounts ia ON ia.id::text = aa.account_id AND ia.user_id = p_user_id
    WHERE aa.date >= CURRENT_DATE - p_days AND (p_account_ids IS NULL OR aa.account_id = ANY(p_account_ids))
    GROUP BY aa.date ORDER BY aa.date ASC;
  ELSE
    RETURN QUERY SELECT aa.date,
      SUM(COALESCE(aa.followers_count,0))::BIGINT, SUM(COALESCE(aa.total_views,0))::BIGINT,
      SUM(COALESCE(aa.total_likes,0))::BIGINT, SUM(COALESCE(aa.total_replies,0))::BIGINT,
      SUM(COALESCE(aa.total_reposts,0))::BIGINT, SUM(COALESCE(aa.total_quotes,0))::BIGINT,
      SUM(COALESCE(aa.total_shares,0))::BIGINT, SUM(COALESCE(aa.total_clicks,0))::BIGINT,
      CASE WHEN SUM(COALESCE(aa.total_views,0)) > 0 THEN
        (SUM(COALESCE(aa.total_likes,0))+SUM(COALESCE(aa.total_replies,0))+SUM(COALESCE(aa.total_reposts,0))+SUM(COALESCE(aa.total_shares,0)))::NUMERIC / SUM(COALESCE(aa.total_views,0))
        ELSE 0 END
    FROM account_analytics aa JOIN accounts a ON a.id = aa.account_id AND a.user_id = p_user_id
    WHERE aa.date >= CURRENT_DATE - p_days AND (p_account_ids IS NULL OR aa.account_id = ANY(p_account_ids))
    GROUP BY aa.date ORDER BY aa.date ASC;
  END IF;
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER;
