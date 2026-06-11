-- Cohort/perf cleanup from the 2026-05-06 audit.
-- - Replace classify_account_cohorts' serial UPDATE ladder with one UPDATE per table.
-- - Add hot-path indexes used by fleet metrics, cohort classification, and media selection.
-- - Drop audited zero-scan indexes that add write overhead.

CREATE INDEX IF NOT EXISTS idx_posts_published_recent_account
  ON public.posts (status, published_at DESC, account_id)
  WHERE status = 'published' AND account_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_posts_published_recent_ig_account
  ON public.posts (status, published_at DESC, instagram_account_id)
  WHERE status = 'published'
    AND platform = 'instagram'
    AND instagram_account_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_media_user_group_recent
  ON public.media (user_id, group_id, created_at DESC)
  WHERE url IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_media_user_folder_recent
  ON public.media (user_id, folder_id, created_at DESC)
  WHERE url IS NOT NULL;

CREATE OR REPLACE FUNCTION public.classify_account_cohorts()
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_threads_count INTEGER := 0;
  v_instagram_count INTEGER := 0;
BEGIN
  WITH post_activity AS (
    SELECT
      account_id,
      BOOL_OR(published_at > NOW() - INTERVAL '24 hours') AS posted_24h,
      BOOL_OR(published_at > NOW() - INTERVAL '7 days') AS posted_7d,
      BOOL_OR(published_at > NOW() - INTERVAL '30 days') AS posted_30d
    FROM public.posts
    WHERE status = 'published'
      AND account_id IS NOT NULL
      AND published_at > NOW() - INTERVAL '30 days'
    GROUP BY account_id
  ),
  desired AS (
    SELECT
      a.id,
      CASE
        WHEN COALESCE(a.followers_count, 0) >= 500
          OR COALESCE(pa.posted_24h, FALSE)
          OR a.last_synced_at > NOW() - INTERVAL '2 hours'
          THEN 'hot'
        WHEN COALESCE(pa.posted_7d, FALSE) THEN 'warm'
        WHEN COALESCE(pa.posted_30d, FALSE) THEN 'cold'
        ELSE 'dormant'
      END AS sync_cohort
    FROM public.accounts a
    LEFT JOIN post_activity pa ON pa.account_id = a.id
    WHERE a.threads_access_token_encrypted IS NOT NULL
  ),
  updated AS (
    UPDATE public.accounts a
    SET
      sync_cohort = d.sync_cohort,
      cohort_updated_at = NOW()
    FROM desired d
    WHERE a.id = d.id
      AND (
        a.sync_cohort IS DISTINCT FROM d.sync_cohort
        OR a.cohort_updated_at IS NULL
        OR a.cohort_updated_at < NOW() - INTERVAL '6 hours'
      )
    RETURNING 1
  )
  SELECT COUNT(*) INTO v_threads_count FROM updated;

  WITH post_activity AS (
    SELECT
      instagram_account_id,
      BOOL_OR(published_at > NOW() - INTERVAL '24 hours') AS posted_24h,
      BOOL_OR(published_at > NOW() - INTERVAL '7 days') AS posted_7d,
      BOOL_OR(published_at > NOW() - INTERVAL '30 days') AS posted_30d
    FROM public.posts
    WHERE status = 'published'
      AND platform = 'instagram'
      AND instagram_account_id IS NOT NULL
      AND published_at > NOW() - INTERVAL '30 days'
    GROUP BY instagram_account_id
  ),
  desired AS (
    SELECT
      ia.id,
      CASE
        WHEN COALESCE(ia.followers_count, 0) >= 500
          OR COALESCE(pa.posted_24h, FALSE)
          OR ia.last_synced_at > NOW() - INTERVAL '2 hours'
          THEN 'hot'
        WHEN COALESCE(pa.posted_7d, FALSE) THEN 'warm'
        WHEN COALESCE(pa.posted_30d, FALSE) THEN 'cold'
        ELSE 'dormant'
      END AS sync_cohort
    FROM public.instagram_accounts ia
    LEFT JOIN post_activity pa ON pa.instagram_account_id = ia.id
    WHERE ia.instagram_access_token_encrypted IS NOT NULL
  ),
  updated AS (
    UPDATE public.instagram_accounts ia
    SET
      sync_cohort = d.sync_cohort,
      cohort_updated_at = NOW()
    FROM desired d
    WHERE ia.id = d.id
      AND (
        ia.sync_cohort IS DISTINCT FROM d.sync_cohort
        OR ia.cohort_updated_at IS NULL
        OR ia.cohort_updated_at < NOW() - INTERVAL '6 hours'
      )
    RETURNING 1
  )
  SELECT COUNT(*) INTO v_instagram_count FROM updated;

  RETURN v_threads_count + v_instagram_count;
END;
$$;

REVOKE EXECUTE ON FUNCTION public.classify_account_cohorts() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.classify_account_cohorts() TO service_role;

DROP INDEX IF EXISTS public.idx_posts_metadata_gin;
DROP INDEX IF EXISTS public.idx_posts_approved_by;
DROP INDEX IF EXISTS public.idx_posts_draft_folder_id;
DROP INDEX IF EXISTS public.idx_accounts_needs_reauth;
DROP INDEX IF EXISTS public.idx_accounts_tags;
DROP INDEX IF EXISTS public.idx_health_snapshots_user;
DROP INDEX IF EXISTS public.idx_health_snapshots_anomaly;
DROP INDEX IF EXISTS public.idx_health_snapshots_growth;
DROP INDEX IF EXISTS public.idx_account_health_snapshots_workspace_id;
DROP INDEX IF EXISTS public.idx_account_health_snapshots_platform;
