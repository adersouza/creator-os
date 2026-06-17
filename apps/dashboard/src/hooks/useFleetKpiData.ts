import { useEffect, useMemo, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';
import { createHookCache, DEFAULT_FRESH_MS } from '@/hooks/_hookCache';
import { useDashboardRefreshRevision } from '@/lib/dashboardRefreshSignal';
import { toDays, toLabel, type TimeRangeInput } from '@/lib/timeRange';
import type { AccountScopeValue } from '@/stores/useAccountScopeStore';
import { withAnalyticsQueryTimeout } from '@/lib/analyticsQueryTimeout';
import { chunkAccountIds } from '@/lib/accountIdBatching';

export type FleetKpiPlatform = 'all' | 'threads' | 'instagram';

/**
 * Aggregated KPI strip data, source = `account_analytics` daily snapshots.
 *
 * `account_analytics` already stores per-day, per-account rollups for both
 * Threads and Instagram, including `total_*` engagement counters and
 * IG-specific fields like `ig_profile_views`, `ig_website_clicks`,
 * `ig_non_follower_reach_pct`. Going through the daily table is significantly
 * cheaper than re-summing per-post, and yields the metric set the spec calls
 * for in the period-compare strip.
 *
 * Two windows are pulled in one round-trip: current window (last `days`),
 * and prior equally-sized window. Per-metric `_delta` is the % change
 * between them (null when prior had zero/no data).
 */
export interface FleetKpiState {
  /** True when current-window daily account_analytics rows exist. */
  hasDailyRows: boolean;
  /** True when current-window published posts exist for this scope. */
  hasPostRows: boolean;
  /** True when headline counters used post-level data because daily rollups were empty. */
  usedPostFallback: boolean;
  igProfileViewsAvailable: boolean;
  igWebsiteClicksAvailable: boolean;
  igNonFollowerReachAvailable: boolean;
  /** Sum of `total_reach` across all in-scope accounts in window. */
  reach: number;
  reachDelta: number | null;
  /** Post-level views/impressions (views_count / ig_views) — distinct from reach. */
  views: number;
  viewsDelta: number | null;
  /** Sum of likes + comments/replies + reposts/quotes + saves + sends/shares. */
  totalInteractions: number;
  totalInteractionsDelta: number | null;
  /** Sum of `total_saves` across IG accounts in window. */
  saves: number;
  savesDelta: number | null;
  /** Sum of `total_shares` (Threads = sends, IG = ig_shares mirrored into total_shares by sync). */
  shares: number;
  sharesDelta: number | null;
  /** Threads-specific. */
  reposts: number;
  repostsDelta: number | null;
  quotes: number;
  quotesDelta: number | null;
  replies: number;
  repliesDelta: number | null;
  /** Sum of `total_clicks` (Threads link clicks + IG website clicks). */
  totalClicks: number;
  totalClicksDelta: number | null;
  /** IG-specific tiles. */
  igProfileViews: number;
  igProfileViewsDelta: number | null;
  igWebsiteClicks: number;
  igWebsiteClicksDelta: number | null;
  igTotalInteractions: number;
  igTotalInteractionsDelta: number | null;
  igNonFollowerReachPct: number | null;
  igNonFollowerReachPctDelta: number | null;
  /** Average `engagement_rate` weighted by reach. */
  engagementRate: number | null;
  engagementRateDelta: number | null;
  /** Save-rate = saves / reach (×100). */
  saveRate: number | null;
  saveRateDelta: number | null;
  /** Send-rate = shares / reach (×100). Threads "amplification" reading. */
  sendRate: number | null;
  sendRateDelta: number | null;
  isLoading: boolean;
  hasError: boolean;
}

const EMPTY: FleetKpiState = {
  hasDailyRows: false,
  hasPostRows: false,
  usedPostFallback: false,
  igProfileViewsAvailable: false,
  igWebsiteClicksAvailable: false,
  igNonFollowerReachAvailable: false,
  reach: 0, reachDelta: null,
  views: 0, viewsDelta: null,
  totalInteractions: 0, totalInteractionsDelta: null,
  saves: 0, savesDelta: null,
  shares: 0, sharesDelta: null,
  reposts: 0, repostsDelta: null,
  quotes: 0, quotesDelta: null,
  replies: 0, repliesDelta: null,
  totalClicks: 0, totalClicksDelta: null,
  igProfileViews: 0, igProfileViewsDelta: null,
  igWebsiteClicks: 0, igWebsiteClicksDelta: null,
  igTotalInteractions: 0, igTotalInteractionsDelta: null,
  igNonFollowerReachPct: null, igNonFollowerReachPctDelta: null,
  engagementRate: null, engagementRateDelta: null,
  saveRate: null, saveRateDelta: null,
  sendRate: null, sendRateDelta: null,
  isLoading: true,
  hasError: false,
};

interface AnalyticsRow {
  account_id: string;
  date: string;
  total_reach: number | null;
  total_likes: number | null;
  total_replies: number | null;
  total_reposts: number | null;
  total_quotes: number | null;
  total_saves: number | null;
  total_shares: number | null;
  total_clicks: number | null;
  ig_profile_views: number | null;
  ig_website_clicks: number | null;
  ig_total_interactions: number | null;
  ig_reach: number | null;
  ig_non_follower_reach_pct: number | null;
  engagement_rate: number | null;
}

interface PostMetricRow {
  account_id: string | null;
  instagram_account_id: string | null;
  platform: 'threads' | 'instagram' | string | null;
  published_at: string | null;
  views_count: number | null;
  likes_count: number | null;
  replies_count: number | null;
  reposts_count: number | null;
  quotes_count: number | null;
  shares_count: number | null;
  ig_reach: number | null;
  ig_views: number | null;
  ig_comment_count: number | null;
  ig_saved: number | null;
  ig_shares: number | null;
}

interface FleetMetricsBucket {
  account_key: string;
  platform: string;
  bucket_date: string;
  total_posts: number | null;
  total_sends: number | null;
  total_saves: number | null;
  total_comments: number | null;
  total_likes: number | null;
  total_reach: number | null;
}

interface FleetMetricsRpcResponse {
  published?: FleetMetricsBucket[] | undefined;
}

type FleetAccountIdsPayload = {
  threadsAcct: Array<{ id: string; username?: string | null | undefined; group_id?: string | null | undefined; followers_count?: number | null | undefined }>;
  igAcct: Array<{ id: string; username?: string | null | undefined; group_id?: string | null | undefined; follower_count?: number | null | undefined }>;
};

const cache = createHookCache<FleetKpiState>();

export function resetFleetKpiDataCache() {
  cache.clearAll();
}

function pctDelta(curr: number, prior: number, minPrior = 10): number | null {
  if (prior < minPrior) return null;
  return Math.round(((curr - prior) / prior) * 1000) / 10;
}

function pctPointDelta(
  curr: number | null,
  prior: number | null,
  priorSample = Number.POSITIVE_INFINITY,
): number | null {
  if (curr == null || prior == null) return null;
  if (priorSample < 10) return null;
  return Math.round((curr - prior) * 10) / 10;
}

function resolveTargetAccountIds(
  accountMeta: FleetAccountIdsPayload,
  platform: FleetKpiPlatform,
  scopedAccount: AccountScopeValue | null,
  accountIds?: string[] | null,
) {
  const include = (id: string, plat: 'threads' | 'instagram') => {
    if (platform === 'threads' && plat !== 'threads') return false;
    if (platform === 'instagram' && plat !== 'instagram') return false;
    if (scopedAccount) return scopedAccount.platform === plat && scopedAccount.id === id;
    if (accountIds && accountIds.length > 0) return accountIds.includes(id);
    return true;
  };

  return {
    threads: accountMeta.threadsAcct
      .filter((row) => include(row.id, 'threads'))
      .map((row) => row.id),
    instagram: accountMeta.igAcct
      .filter((row) => include(row.id, 'instagram'))
      .map((row) => row.id),
  };
}

function aggregate(
  rows: AnalyticsRow[],
  ownedThreadIds: Set<string>,
  ownedIgIds: Set<string>,
  platform: FleetKpiPlatform,
  scopedAccount: AccountScopeValue | null,
  accountIds?: string[] | null,
) {
  let reach = 0,
    likes = 0,
    replies = 0,
    reposts = 0,
    quotes = 0,
    saves = 0,
    shares = 0,
    totalClicks = 0,
    igProfileViews = 0,
    igWebsiteClicks = 0,
    igTotalInteractions = 0,
    igReach = 0;
  // Reach-weighted averages for ratios.
  let nonFollowerReachWeighted = 0;
  let nonFollowerReachWeight = 0;
  let engagementRateWeighted = 0;
  let engagementRateWeight = 0;

  for (const r of rows) {
    const isThreads = ownedThreadIds.has(r.account_id);
    const isIg = ownedIgIds.has(r.account_id);
    if (!isThreads && !isIg) continue;
    if (platform === 'threads' && !isThreads) continue;
    if (platform === 'instagram' && !isIg) continue;
    if (scopedAccount && scopedAccount.id !== r.account_id) continue;
    if (!scopedAccount && accountIds && accountIds.length > 0 && !accountIds.includes(r.account_id)) continue;

    const rowReach = isIg ? r.total_reach ?? r.ig_reach ?? 0 : r.total_reach ?? 0;
    reach += rowReach;
    likes += r.total_likes ?? 0;
    replies += r.total_replies ?? 0;
    reposts += r.total_reposts ?? 0;
    quotes += r.total_quotes ?? 0;
    saves += r.total_saves ?? 0;
    shares += r.total_shares ?? 0;
    totalClicks += r.total_clicks ?? 0;

    if (isIg) {
      igProfileViews += r.ig_profile_views ?? 0;
      igWebsiteClicks += r.ig_website_clicks ?? 0;
      igTotalInteractions += r.ig_total_interactions ?? 0;
      igReach += r.ig_reach ?? 0;
      if (r.ig_non_follower_reach_pct != null && r.ig_reach != null && r.ig_reach > 0) {
        nonFollowerReachWeighted += r.ig_non_follower_reach_pct * r.ig_reach;
        nonFollowerReachWeight += r.ig_reach;
      }
    }

    if (r.engagement_rate != null && rowReach > 0) {
      engagementRateWeighted += r.engagement_rate * rowReach;
      engagementRateWeight += rowReach;
    }
  }

  const totalInteractions = likes + replies + reposts + quotes + saves + shares;
  return {
    reach,
    likes,
    replies,
    reposts,
    quotes,
    saves,
    shares,
    totalClicks,
    igProfileViews,
    igWebsiteClicks,
    igTotalInteractions,
    igReach,
    totalInteractions,
    nonFollowerReachPct:
      nonFollowerReachWeight > 0
        ? Math.round((nonFollowerReachWeighted / nonFollowerReachWeight) * 10) / 10
        : null,
    engagementRate:
      engagementRateWeight > 0
        ? Math.round((engagementRateWeighted / engagementRateWeight) * 100) / 100
        : reach > 0
          ? Math.round((totalInteractions / reach) * 100 * 100) / 100
          : null,
    saveRate: reach > 0 ? Math.round((saves / reach) * 100 * 100) / 100 : null,
    sendRate: reach > 0 ? Math.round((shares / reach) * 100 * 100) / 100 : null,
  };
}

function aggregatePosts(
  rows: PostMetricRow[],
  ownedThreadIds: Set<string>,
  ownedIgIds: Set<string>,
  platform: FleetKpiPlatform,
  scopedAccount: AccountScopeValue | null,
  accountIds?: string[] | null,
) {
  let reach = 0,
    views = 0,
    likes = 0,
    replies = 0,
    reposts = 0,
    quotes = 0,
    saves = 0,
    shares = 0;

  for (const row of rows) {
    const possibleIgAccountId = row.instagram_account_id ?? row.account_id;
    const isIg =
      row.platform === 'instagram' ||
      !!row.instagram_account_id ||
      (possibleIgAccountId ? ownedIgIds.has(possibleIgAccountId) : false);
    const accountId = isIg ? possibleIgAccountId : row.account_id;
    if (!accountId) continue;
    const ownedByIgId = ownedIgIds.has(accountId);
    const ownedByThreadAccountId = row.account_id ? ownedThreadIds.has(row.account_id) : false;
    if (isIg && !ownedByIgId && !ownedByThreadAccountId) continue;
    if (!isIg && !ownedThreadIds.has(accountId)) continue;
    if (platform === 'instagram' && !isIg) continue;
    if (platform === 'threads' && isIg) continue;
    if (scopedAccount && scopedAccount.id !== accountId) continue;
    if (!scopedAccount && accountIds && accountIds.length > 0 && !accountIds.includes(accountId)) continue;

    const rowReach = isIg
      ? row.ig_reach ?? row.ig_views ?? row.views_count ?? 0
      : row.views_count ?? 0;
    reach += rowReach;
    // True views/impressions (distinct from reach): IG video/reel views, else
    // post view counts. This is the only views source — the daily analytics
    // rollup has no views column.
    const rowViews = isIg
      ? row.ig_views ?? row.views_count ?? 0
      : row.views_count ?? 0;
    views += rowViews;
    likes += row.likes_count ?? 0;
    replies += isIg ? row.ig_comment_count ?? row.replies_count ?? 0 : row.replies_count ?? 0;
    reposts += isIg ? 0 : row.reposts_count ?? 0;
    quotes += isIg ? 0 : row.quotes_count ?? 0;
    saves += isIg ? row.ig_saved ?? 0 : 0;
    shares += isIg ? row.ig_shares ?? row.shares_count ?? 0 : row.shares_count ?? 0;
  }

  const totalInteractions = likes + replies + reposts + quotes + saves + shares;
  return {
    reach,
    views,
    likes,
    replies,
    reposts,
    quotes,
    saves,
    shares,
    totalClicks: 0,
    igProfileViews: 0,
    igWebsiteClicks: 0,
    igTotalInteractions: totalInteractions,
    igReach: platform === 'threads' ? 0 : reach,
    totalInteractions,
    nonFollowerReachPct: null,
    engagementRate: reach > 0 ? Math.round((totalInteractions / reach) * 100 * 100) / 100 : null,
    saveRate: reach > 0 ? Math.round((saves / reach) * 100 * 100) / 100 : null,
    sendRate: reach > 0 ? Math.round((shares / reach) * 100 * 100) / 100 : null,
  };
}

function aggregateFleetBuckets(
  rows: FleetMetricsBucket[],
  ownedThreadIds: Set<string>,
  ownedIgIds: Set<string>,
  platform: FleetKpiPlatform,
  scopedAccount: AccountScopeValue | null,
  accountIds?: string[] | null,
) {
  let reach = 0,
    likes = 0,
    replies = 0,
    saves = 0,
    shares = 0,
    posts = 0;

  for (const row of rows) {
    const isIg = row.platform === 'instagram';
    const isThreads = row.platform === 'threads';
    if (isIg && !ownedIgIds.has(row.account_key)) continue;
    if (isThreads && !ownedThreadIds.has(row.account_key)) continue;
    if (!isIg && !isThreads) continue;
    if (platform === 'instagram' && !isIg) continue;
    if (platform === 'threads' && !isThreads) continue;
    if (scopedAccount && (scopedAccount.platform !== row.platform || scopedAccount.id !== row.account_key)) continue;
    if (!scopedAccount && accountIds && accountIds.length > 0 && !accountIds.includes(row.account_key)) continue;

    reach += Number(row.total_reach) || 0;
    likes += Number(row.total_likes) || 0;
    replies += Number(row.total_comments) || 0;
    saves += Number(row.total_saves) || 0;
    shares += Number(row.total_sends) || 0;
    posts += Number(row.total_posts) || 0;
  }

  const totalInteractions = likes + replies + saves + shares;
  return {
    reach,
    likes,
    replies,
    reposts: 0,
    quotes: 0,
    saves,
    shares,
    totalClicks: 0,
    igProfileViews: 0,
    igWebsiteClicks: 0,
    igTotalInteractions: totalInteractions,
    igReach: platform === 'threads' ? 0 : reach,
    totalInteractions,
    postCount: posts,
    nonFollowerReachPct: null,
    engagementRate: reach > 0 ? Math.round((totalInteractions / reach) * 100 * 100) / 100 : null,
    saveRate: reach > 0 ? Math.round((saves / reach) * 100 * 100) / 100 : null,
    sendRate: reach > 0 ? Math.round((shares / reach) * 100 * 100) / 100 : null,
  };
}

const cacheKey = (
  user: string | null,
  rangeLabel: string,
  platform: FleetKpiPlatform,
  scopedAccount: AccountScopeValue | null,
  accountIds?: string[] | null,
  groupId?: string | null,
) =>
  user
    ? `${user}:${rangeLabel}:${platform}:${scopedAccount?.platform ?? 'all'}:${scopedAccount?.id ?? 'fleet'}:${groupId ?? 'all'}:${accountIds?.join(',') ?? 'fleet'}`
    : null;

export function useFleetKpiData(
  range: TimeRangeInput,
  platform: FleetKpiPlatform,
  scopedAccount: AccountScopeValue | null = null,
  accountIds?: string[],
  groupId?: string | null,
): FleetKpiState {
  const authUser = useAuthUser();
  const userKey = authUser?.id ?? null;
  const refreshRevision = useDashboardRefreshRevision();
  const queryClient = useQueryClient();
  const rangeForDays = typeof range === 'number' ? { days: range } : range;
  const days = toDays(rangeForDays);
  const rangeLabel = toLabel(rangeForDays);
  const reactQueryKey = useMemo(
    () => [
      'fleetKpiData',
      userKey,
      rangeLabel,
      platform,
      scopedAccount?.platform ?? 'all',
      scopedAccount?.id ?? 'fleet',
      groupId ?? 'all',
      accountIds?.join(',') ?? null,
    ] as const,
    [userKey, rangeLabel, platform, scopedAccount?.platform, scopedAccount?.id, groupId, accountIds],
  );
  const [state, setState] = useState<FleetKpiState>(() => {
    const persisted = queryClient.getQueryData<FleetKpiState>(reactQueryKey);
    if (persisted) return { ...EMPTY, ...persisted, isLoading: false };
    const cached = cache.get(cacheKey(userKey, rangeLabel, platform, scopedAccount, accountIds, groupId));
    return cached ? { ...EMPTY, ...cached, isLoading: false } : EMPTY;
  });

  useEffect(() => {
    void refreshRevision;
    let cancelled = false;
    if (!authUser) return;

    const key = cacheKey(userKey, rangeLabel, platform, scopedAccount, accountIds, groupId);
    const persisted = queryClient.getQueryData<FleetKpiState>(reactQueryKey);
    if (persisted) setState({ ...EMPTY, ...persisted, isLoading: false });
    const cached = cache.get(key);
    if (cached) setState({ ...cached, isLoading: false });
    const queryState = queryClient.getQueryState(reactQueryKey);
    if (
      queryState?.dataUpdatedAt &&
      !queryState.isInvalidated &&
      Date.now() - queryState.dataUpdatedAt < DEFAULT_FRESH_MS
    ) return;
    if (cache.isFresh(key)) return;

    void queryClient.fetchQuery<FleetKpiState>({
      queryKey: reactQueryKey,
      staleTime: DEFAULT_FRESH_MS,
      queryFn: async () => {
      const now = new Date();
      const windowStart = new Date(now.getTime() - days * 86_400_000);
      const priorStart = new Date(now.getTime() - 2 * days * 86_400_000);
      const isoDate = (d: Date) => d.toISOString().slice(0, 10);

      const rawMetricsKey = ['fleetMetricsRaw', authUser.id, rangeLabel] as const;
      const accountMetaKey = ['fleetAccountMeta', authUser.id] as const;

      const accountMeta = await queryClient.fetchQuery<FleetAccountIdsPayload>({
        queryKey: accountMetaKey,
        staleTime: 5 * 60_000,
        queryFn: async () => {
          const [threadsAcctRes, igAcctRes] = await Promise.all([
            supabase
              .from('accounts')
              .select('id, username, group_id, followers_count')
              .eq('user_id', authUser.id)
              .eq('is_active', true)
              .eq('is_retired', false),
            supabase
              .from('instagram_accounts')
              .select('id, username, group_id, follower_count')
              .eq('user_id', authUser.id)
              .eq('is_active', true),
          ]);
          if (threadsAcctRes.error) throw threadsAcctRes.error;
          if (igAcctRes.error) throw igAcctRes.error;
          return {
            threadsAcct: threadsAcctRes.data ?? [],
            igAcct: igAcctRes.data ?? [],
          };
        },
      });

      const targetIds = resolveTargetAccountIds(accountMeta, platform, scopedAccount, accountIds);
      const analyticsAccountIds = [...targetIds.threads, ...targetIds.instagram];
      if (analyticsAccountIds.length === 0) {
        const next = { ...EMPTY, isLoading: false, hasError: false };
        cache.set(key, next);
        return next;
      }

      let postsQuery = supabase
        .from('posts')
        .select(
          'account_id, instagram_account_id, platform, published_at, views_count, likes_count, replies_count, reposts_count, quotes_count, shares_count, ig_reach, ig_views, ig_comment_count, ig_saved, ig_shares',
        )
        .eq('user_id', authUser.id)
        .eq('status', 'published')
        .gte('published_at', priorStart.toISOString())
        .lte('published_at', now.toISOString());

      if (scopedAccount && targetIds.threads.length > 0 && targetIds.instagram.length === 0) {
        postsQuery = postsQuery.eq('account_id', scopedAccount.id);
      } else if (scopedAccount && targetIds.instagram.length > 0) {
        postsQuery = postsQuery.eq('instagram_account_id', scopedAccount.id);
      } else if (!scopedAccount && analyticsAccountIds.length <= 10 && targetIds.threads.length > 0 && targetIds.instagram.length > 0) {
        const accountColumnIds = [...targetIds.threads, ...targetIds.instagram];
        postsQuery = postsQuery.or(
          `account_id.in.(${accountColumnIds.join(',')}),instagram_account_id.in.(${targetIds.instagram.join(',')})`,
        );
      } else if (!scopedAccount && analyticsAccountIds.length <= 10 && targetIds.threads.length > 0) {
        postsQuery = postsQuery.in('account_id', targetIds.threads);
      } else if (!scopedAccount && analyticsAccountIds.length <= 10) {
        postsQuery = postsQuery.or(
          `account_id.in.(${targetIds.instagram.join(',')}),instagram_account_id.in.(${targetIds.instagram.join(',')})`,
        );
      }

      const analyticsRowsPromise = Promise.all(
        chunkAccountIds(analyticsAccountIds).map((ids) =>
          supabase
            .from('account_analytics')
            .select(
              'account_id, date, total_reach, total_likes, total_replies, total_reposts, total_quotes, total_saves, total_shares, total_clicks, ig_profile_views, ig_website_clicks, ig_total_interactions, ig_reach, ig_non_follower_reach_pct, engagement_rate',
            )
            .in('account_id', ids)
            .gte('date', isoDate(priorStart))
            .lte('date', isoDate(now))
            .limit(20000),
        ),
      );

      const [analyticsChunkResults, postsRes, fleetRpcData] = await withAnalyticsQueryTimeout(Promise.all([
        analyticsRowsPromise,
        postsQuery.limit(20000),
        queryClient.fetchQuery<FleetMetricsRpcResponse>({
          queryKey: rawMetricsKey,
          staleTime: DEFAULT_FRESH_MS,
          queryFn: async () => {
            const { data, error } = await supabase.rpc('get_fleet_metrics', {
              p_user_id: authUser.id,
              p_window_start: priorStart.toISOString(),
              p_window_end: now.toISOString(),
            });
            if (error) throw error;
            return (data ?? { published: [] }) as FleetMetricsRpcResponse;
          },
        }),
      ]), 'fleet KPI strip');

      const analyticsError = analyticsChunkResults.find((result) => result.error)?.error;
      if (analyticsError) throw analyticsError;
      if (postsRes.error) throw postsRes.error;

      const ownedThreadIds = new Set<string>(
        accountMeta.threadsAcct.map((r) => r.id as string),
      );
      const ownedIgIds = new Set<string>(
        accountMeta.igAcct.map((r) => r.id as string),
      );

      const rows = analyticsChunkResults.flatMap((result) => (result.data ?? []) as AnalyticsRow[]);
      const windowStartDate = isoDate(windowStart);
      const priorEndDate = windowStartDate;
      const current: AnalyticsRow[] = [];
      const prior: AnalyticsRow[] = [];
      for (const row of rows) {
        if (row.date >= windowStartDate) current.push(row);
        else if (row.date < priorEndDate) prior.push(row);
      }

      const postRows = ((postsRes.data ?? []) as PostMetricRow[]).filter((row) => row.published_at);
      const currentPosts: PostMetricRow[] = [];
      const priorPosts: PostMetricRow[] = [];
      for (const row of postRows) {
        const publishedAt = row.published_at ? new Date(row.published_at) : null;
        if (!publishedAt) continue;
        if (publishedAt >= windowStart) currentPosts.push(row);
        else if (publishedAt >= priorStart && publishedAt < windowStart) priorPosts.push(row);
      }

      const dailyCurrent = aggregate(current, ownedThreadIds, ownedIgIds, platform, scopedAccount, accountIds);
      const dailyPrior = aggregate(prior, ownedThreadIds, ownedIgIds, platform, scopedAccount, accountIds);
      const postCurrent = aggregatePosts(currentPosts, ownedThreadIds, ownedIgIds, platform, scopedAccount, accountIds);
      const postPrior = aggregatePosts(priorPosts, ownedThreadIds, ownedIgIds, platform, scopedAccount, accountIds);
      const fleetBuckets = fleetRpcData.published ?? [];
      const rpcCurrentBuckets: FleetMetricsBucket[] = [];
      const rpcPriorBuckets: FleetMetricsBucket[] = [];
      for (const bucket of fleetBuckets) {
        if (bucket.bucket_date >= windowStartDate) rpcCurrentBuckets.push(bucket);
        else rpcPriorBuckets.push(bucket);
      }
      const rpcCurrent = aggregateFleetBuckets(rpcCurrentBuckets, ownedThreadIds, ownedIgIds, platform, scopedAccount, accountIds);
      const rpcPrior = aggregateFleetBuckets(rpcPriorBuckets, ownedThreadIds, ownedIgIds, platform, scopedAccount, accountIds);
      const useRpcFallback = dailyCurrent.reach <= 0 && rpcCurrent.reach > 0;
      const usePostFallback = !useRpcFallback && dailyCurrent.reach <= 0 && postCurrent.reach > 0;
      const c = useRpcFallback ? rpcCurrent : usePostFallback ? postCurrent : dailyCurrent;
      const p = useRpcFallback ? rpcPrior : usePostFallback ? postPrior : dailyPrior;
      const igProfileViewsAvailable = current.some((row) => row.ig_profile_views != null);
      const igWebsiteClicksAvailable = current.some((row) => row.ig_website_clicks != null);
      const igNonFollowerReachAvailable = current.some((row) => row.ig_non_follower_reach_pct != null);

      const next: FleetKpiState = {
        hasDailyRows: current.length > 0,
        hasPostRows: currentPosts.length > 0 || rpcCurrent.postCount > 0,
        usedPostFallback: useRpcFallback || usePostFallback,
        igProfileViewsAvailable,
        igWebsiteClicksAvailable,
        igNonFollowerReachAvailable,
        reach: c.reach,
        reachDelta: pctDelta(c.reach, p.reach),
        // Views always come from post-level data (the daily rollup has none).
        views: postCurrent.views,
        viewsDelta: pctDelta(postCurrent.views, postPrior.views),
        totalInteractions: c.totalInteractions,
        totalInteractionsDelta: pctDelta(c.totalInteractions, p.totalInteractions),
        saves: c.saves,
        savesDelta: pctDelta(c.saves, p.saves),
        shares: c.shares,
        sharesDelta: pctDelta(c.shares, p.shares),
        reposts: c.reposts,
        repostsDelta: pctDelta(c.reposts, p.reposts),
        quotes: c.quotes,
        quotesDelta: pctDelta(c.quotes, p.quotes),
        replies: c.replies,
        repliesDelta: pctDelta(c.replies, p.replies),
        totalClicks: c.totalClicks,
        totalClicksDelta: pctDelta(c.totalClicks, p.totalClicks),
        igProfileViews: c.igProfileViews,
        igProfileViewsDelta: pctDelta(c.igProfileViews, p.igProfileViews),
        igWebsiteClicks: c.igWebsiteClicks,
        igWebsiteClicksDelta: pctDelta(c.igWebsiteClicks, p.igWebsiteClicks),
        igTotalInteractions: c.igTotalInteractions,
        igTotalInteractionsDelta: pctDelta(c.igTotalInteractions, p.igTotalInteractions),
        igNonFollowerReachPct: c.nonFollowerReachPct,
        igNonFollowerReachPctDelta: pctPointDelta(c.nonFollowerReachPct, p.nonFollowerReachPct),
        engagementRate: c.engagementRate,
        engagementRateDelta: pctPointDelta(c.engagementRate, p.engagementRate, p.reach),
        saveRate: c.saveRate,
        saveRateDelta: pctPointDelta(c.saveRate, p.saveRate, p.reach),
        sendRate: c.sendRate,
        sendRateDelta: pctPointDelta(c.sendRate, p.sendRate, p.reach),
        isLoading: false,
        hasError: false,
      };
      cache.set(key, next);
      return next;
      },
    }).then((next) => {
      if (!cancelled) setState(next);
    }).catch(() => {
      if (!cancelled) {
        setState((prev) => {
          const hasUsablePayload =
            prev.reach > 0 ||
            prev.totalInteractions > 0 ||
            prev.igProfileViews > 0 ||
            prev.igWebsiteClicks > 0 ||
            prev.engagementRate != null ||
            prev.saveRate != null ||
            prev.sendRate != null ||
            prev.igNonFollowerReachPct != null;
          return { ...prev, isLoading: false, hasError: !hasUsablePayload };
        });
      }
    });

    return () => { cancelled = true; };
  }, [userKey, days, rangeLabel, platform, authUser, scopedAccount, accountIds, groupId, refreshRevision, queryClient, reactQueryKey]);

  return state;
}
