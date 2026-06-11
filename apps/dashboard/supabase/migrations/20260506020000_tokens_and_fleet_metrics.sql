-- Flag already-expired Threads/Instagram tokens and add the fleet metrics
-- covering index identified by the production timeout audit.

DO $$
BEGIN
  IF to_regclass('public.accounts') IS NOT NULL
    AND EXISTS (
      SELECT 1
      FROM information_schema.columns
      WHERE table_schema = 'public'
        AND table_name = 'accounts'
        AND column_name IN ('token_expires_at', 'needs_reauth', 'is_active', 'status', 'updated_at')
      GROUP BY table_schema, table_name
      HAVING count(*) = 5
    )
  THEN
    UPDATE public.accounts
    SET
      needs_reauth = true,
      is_active = false,
      status = 'needs_reauth',
      updated_at = now()
    WHERE token_expires_at < now()
      AND needs_reauth = false;
  END IF;
END $$;

ALTER TABLE IF EXISTS public.instagram_accounts
  ADD COLUMN IF NOT EXISTS status text;

DO $$
BEGIN
  IF to_regclass('public.instagram_accounts') IS NOT NULL
    AND EXISTS (
      SELECT 1
      FROM information_schema.columns
      WHERE table_schema = 'public'
        AND table_name = 'instagram_accounts'
        AND column_name IN ('token_expires_at', 'needs_reauth', 'is_active', 'status', 'updated_at')
      GROUP BY table_schema, table_name
      HAVING count(*) = 5
    )
  THEN
    UPDATE public.instagram_accounts
    SET
      needs_reauth = true,
      is_active = false,
      status = 'needs_reauth',
      updated_at = now()
    WHERE token_expires_at < now()
      AND needs_reauth = false;
  END IF;
END $$;

DO $$
BEGIN
  IF to_regclass('public.posts') IS NOT NULL
    AND EXISTS (
      SELECT 1
      FROM information_schema.columns
      WHERE table_schema = 'public'
        AND table_name = 'posts'
        AND column_name IN (
          'user_id',
          'status',
          'published_at',
          'account_id',
          'platform',
          'likes_count',
          'views_count',
          'replies_count',
          'shares_count',
          'ig_reach',
          'ig_shares',
          'ig_saved',
          'ig_comment_count'
        )
      GROUP BY table_schema, table_name
      HAVING count(*) = 13
    )
  THEN
    EXECUTE $index$
      CREATE INDEX IF NOT EXISTS idx_posts_fleet_metrics
        ON public.posts (user_id, status, published_at DESC)
        INCLUDE (
          account_id,
          platform,
          likes_count,
          views_count,
          replies_count,
          shares_count,
          ig_reach,
          ig_shares,
          ig_saved,
          ig_comment_count
        )
    $index$;
  END IF;
END $$;
