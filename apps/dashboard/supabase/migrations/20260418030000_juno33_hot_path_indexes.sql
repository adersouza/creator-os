-- Hot-path indexes for juno33's client-side direct-Supabase queries.
--
-- Audit (2026-04-18) surfaced three missing composites that are currently
-- forcing bitmap intersections of single-column indexes. At ≥50k posts per
-- user each of these is 5–50× slower than a native composite.
--
-- Scope: add-only, no drops. CONCURRENTLY so there's no table lock.

-- 1. Restore needs_reauth partial index (regressed in 20260306100638_drop_unused_indexes_batch1).
--    juno33 hooks useNeedsAttention / useFleetHealth / useActivityEvents all
--    query WHERE needs_reauth = true on accounts + instagram_accounts.
CREATE INDEX IF NOT EXISTS idx_accounts_needs_reauth
  ON public.accounts (user_id, updated_at DESC)
  WHERE needs_reauth = true;

CREATE INDEX IF NOT EXISTS idx_instagram_accounts_needs_reauth
  ON public.instagram_accounts (user_id, updated_at DESC)
  WHERE needs_reauth = true;

-- 2. Composite (user_id, status, scheduled_for) on posts.
--    Matches useNextUpPosts, useFleetTotals, useSystemStatus, useCalendarPosts,
--    useNeedsAttention — every query doing status='scheduled' + date range.
CREATE INDEX IF NOT EXISTS idx_posts_user_status_scheduled_for
  ON public.posts (user_id, status, scheduled_for)
  WHERE status = 'scheduled';

-- 3. Partial (user_id, published_at DESC) for published-only activity feeds.
--    useActivityEvents sorts by published_at DESC LIMIT 40; a status-partial
--    index beats filtering idx_posts_user_published after the fact.
CREATE INDEX IF NOT EXISTS idx_posts_user_published_at_desc
  ON public.posts (user_id, published_at DESC)
  WHERE status = 'published';

-- 4. Composite for fleet-status filters on accounts.
--    useConnectedAccounts / useFleetHealth join on
--    (user_id + is_active + is_retired). Separate single-column indexes force
--    a bitmap AND; a composite is one index scan.
CREATE INDEX IF NOT EXISTS idx_accounts_user_active_retired
  ON public.accounts (user_id, is_active, is_retired)
  WHERE is_active = true AND is_retired = false;

CREATE INDEX IF NOT EXISTS idx_instagram_accounts_user_active
  ON public.instagram_accounts (user_id, is_active)
  WHERE is_active = true;
