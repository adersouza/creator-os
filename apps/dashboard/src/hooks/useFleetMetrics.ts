import { useEffect, useMemo, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';
import { createHookCache, DEFAULT_FRESH_MS } from '@/hooks/_hookCache';
import { useDashboardRefreshRevision } from '@/lib/dashboardRefreshSignal';
import { withAnalyticsQueryTimeout } from '@/lib/analyticsQueryTimeout';
import {
  eqsForSignals,
  fillDateRange,
  type PostSignals,
} from '@/lib/eqs';
import { toLabel, type TimeRangeInput } from '@/lib/timeRange';
import type { AccountScopeValue } from '@/stores/useAccountScopeStore';
import { chunkAccountIds } from '@/lib/accountIdBatching';

export type FleetMetricsTimeframe = TimeRangeInput;
export type FleetMetricsPlatform = 'all' | 'threads' | 'instagram';

function timeframeKey(tf: FleetMetricsTimeframe): string {
  return toLabel(typeof tf === 'number' ? { days: tf } : tf);
}

/** One day in the EQS trend series. */
export interface FleetMetricsPoint {
  /** ISO date (YYYY-MM-DD) for the bucket. */
  date: string;
  /** EQS score for that day (0-100), computed across the posts published on that day. */
  eqs: number;
  /** Raw reach (views) for the bucket — exposed so consumers can render secondary overlays. */
  reach: number;
}

/** Per-account aggregated metrics in the selected window (for leaderboards). */
export interface FleetAccountAggregate {
  accountId: string;
  platform: 'threads' | 'instagram';
  username: string | null;
  groupId: string | null;
  /** 0–100 EQS computed from post engagement in the window. */
  eqs: number;
  reach: number;
  sends: number;
  saves: number;
  comments: number;
  likes: number;
  posts: number;
  /** Reach in the prior equally-sized window — needed for honest per-account
   *  Δ% in fleet leaderboards. 0 when the account had no posts in the prior. */
  priorReach: number;
  priorPosts: number;
  /** % change in reach vs prior window. null when prior had no data. */
  reachDeltaPct: number | null;
  /** Follower growth % across the window for this account. null = not enough history. */
  followerGrowthPct: number | null;
}

export interface FleetMetricsState {
  /** Rolled-up EQS across the whole fleet inside the window (0-100). */
  eqs: number;
  /** Delta in EQS points vs the prior equally-sized window. null when prior period has no posts. */
  eqsDelta: number | null;
  /** Sum of views_count across all in-window posts. */
  totalReach: number;
  /** % change in reach vs prior window. */
  reachDeltaPct: number | null;
  /** sends + saves raw sum. */
  sendsPlusSaves: number;
  sendsPlusSavesDeltaPct: number | null;
  /** 0-100 published / (published + failed) for posts that landed in the window. */
  scheduleCompliance: number | null;
  scheduleComplianceDelta: number | null;
  /**
   * Follower growth % across the window (end snapshot vs window-open snapshot).
   * null when we don't have enough history to compute it — the widget should empty-state.
   */
  followerGrowthPct: number | null;
  followerGrowthDeltaPct: number | null;
  /** Daily EQS + reach series — length = window size in days. */
  series: FleetMetricsPoint[];
  /** Per-account aggregates, sorted by EQS descending. */
  accounts: FleetAccountAggregate[];
  /** Count of posts used to build aggregates. */
  postCount: number;
  /**
   * Count of posts that cleared the EQS reach floor (>= MIN_REACH_FOR_EQS=50)
   * inside the current window — i.e., the actual sample size feeding the
   * EQS calculation. Used by `shouldAuditQwe` to suppress perfect-score
   * outputs that are driven by a handful of qualifying posts. Falls back to
   * 0 if the RPC predates v6 (eqs_post_count missing on the bucket payload).
   */
  eqsQualifyingPostCount: number;
  isLoading: boolean;
  hasError: boolean;
}

const EMPTY_FLEET_METRICS_STATE: FleetMetricsState = {
  eqs: 0,
  eqsDelta: null,
  totalReach: 0,
  reachDeltaPct: null,
  sendsPlusSaves: 0,
  sendsPlusSavesDeltaPct: null,
  scheduleCompliance: null,
  scheduleComplianceDelta: null,
  followerGrowthPct: null,
  followerGrowthDeltaPct: null,
  series: [],
  accounts: [],
  postCount: 0,
  eqsQualifyingPostCount: 0,
  isLoading: true,
  hasError: false,
};

type AccountRow = {
  id: string;
  username: string | null;
  group_id: string | null;
  followers_count?: number | null | undefined;
  follower_count?: number | null | undefined;
};

/** One bucket from get_fleet_metrics RPC: (account, day, platform) pre-aggregate.
 *  `eqs_post_count` is optional so older RPC versions (pre-v6 deploy) keep
 *  working — when absent, the qualifying-post total falls back to 0 and the
 *  audit gate uses its quality-action heuristic alone. */
type PublishedBucket = {
  account_key: string;
  platform: string;
  bucket_date: string;
  total_posts: number;
  total_sends: number;
  total_saves: number;
  total_comments: number;
  total_likes: number;
  total_reach: number;
  eqs_sends: number;
  eqs_saves: number;
  eqs_comments: number;
  eqs_likes: number;
  eqs_reach: number;
  eqs_post_count?: number | undefined;
};
type FailedBucket = {
  account_key: string;
  platform: string;
  bucket_date: string;
  failed_count: number;
};
type FleetMetricsRpcResponse = {
  published: PublishedBucket[];
  failed: FailedBucket[];
};

type FleetAccountMetaPayload = {
  threadsAcct: AccountRow[];
  igAcct: AccountRow[];
};

type FleetHistoryPayload = {
  history: Array<{ account_id: string; platform: string; date: string; followers_count: number | null }>;
  historySeed: Array<{ account_id: string; platform: string; date: string; followers_count: number | null }>;
};

/** Coerce a bucket's eqs_* fields into PostSignals so eqsForSignals can consume it. */
function bucketToEqsSignals(b: PublishedBucket): PostSignals {
  return {
    sends: Number(b.eqs_sends) || 0,
    saves: Number(b.eqs_saves) || 0,
    comments: Number(b.eqs_comments) || 0,
    likes: Number(b.eqs_likes) || 0,
    reach: Number(b.eqs_reach) || 0,
  };
}

function pctDelta(current: number, prior: number, minPrior = 10): number | null {
  if (prior < minPrior) return null;
  return Math.round(((current - prior) / prior) * 1000) / 10;
}

/**
 * Fleet-wide Overview metrics for the KPI strip, EQS hero chart, and leaderboards.
 *
 * Reads `posts` engagement columns inside the selected window and rolls them up to:
 *   - Fleet EQS + daily series
 *   - Total reach, sends+saves, schedule compliance
 *   - Per-account aggregates (for Top/Underperforming leaderboards)
 *   - Follower growth % via `account_metrics_history` (or null when insufficient history)
 *
 * Follows the same pattern as the other dashboard hooks (useFleetHealth, useNextUpPosts):
 * gated on useAuthUser, cancels on unmount, normalizes to widget-friendly shape.
 */
const cache = createHookCache<FleetMetricsState>();
const rawFleetMetricsCache = new Map<
  string,
  { updatedAt: number; value: FleetMetricsRpcResponse }
>();
const rawFleetMetricsInFlight = new Map<string, Promise<FleetMetricsRpcResponse>>();
const metricsCacheKey = (
  user: string | null,
  timeframeKeyValue: string,
  platform: string,
  scopedAccount: AccountScopeValue | null,
  accountIds?: string[] | null,
  groupId?: string | null,
) =>
  user
    ? `${user}:${timeframeKeyValue}:${platform}:${scopedAccount?.platform ?? 'all'}:${scopedAccount?.id ?? 'fleet'}:${groupId ?? 'all'}:${accountIds?.join(',') ?? 'fleet'}`
    : null;

export function resetFleetMetricsCache() {
  cache.clearAll();
  rawFleetMetricsCache.clear();
  rawFleetMetricsInFlight.clear();
}

async function fetchFleetMetricsRpc(
  cacheKey: string,
  userId: string,
  windowStartIso: string,
  windowEndIso: string,
): Promise<FleetMetricsRpcResponse> {
  const cached = rawFleetMetricsCache.get(cacheKey);
  if (cached && Date.now() - cached.updatedAt < DEFAULT_FRESH_MS) {
    return cached.value;
  }
  if (cached) rawFleetMetricsCache.delete(cacheKey);

  const existing = rawFleetMetricsInFlight.get(cacheKey);
  if (existing) return existing;

  const request = (async () => {
    const { data, error } = await supabase.rpc('get_fleet_metrics', {
      p_user_id: userId,
      p_window_start: windowStartIso,
      p_window_end: windowEndIso,
    });
    if (error) throw new Error(error.message ?? JSON.stringify(error));
    const value = (data ?? { published: [], failed: [] }) as FleetMetricsRpcResponse;
    rawFleetMetricsCache.set(cacheKey, { updatedAt: Date.now(), value });
    return value;
  })().finally(() => {
    if (rawFleetMetricsInFlight.get(cacheKey) === request) {
      rawFleetMetricsInFlight.delete(cacheKey);
    }
  });

  rawFleetMetricsInFlight.set(cacheKey, request);
  return request;
}

export interface UseFleetMetricsOptions {
  /** When false, the hook still mounts (rules of hooks) but skips the network
   *  fetch. Used when a parent passes pre-fetched metrics down so children
   *  don't redundantly trigger the same RPC. Defaults to true. */
  enabled?: boolean | undefined;
  accountIds?: string[] | undefined;
  groupId?: string | null | undefined;
}

// Signature pattern: positional core args plus an options object for secondary scope controls.
export function useFleetMetrics(
  timeframe: FleetMetricsTimeframe,
  platform: FleetMetricsPlatform,
  scopedAccount: AccountScopeValue | null = null,
  options: UseFleetMetricsOptions = {},
): FleetMetricsState {
  const { enabled = true, accountIds, groupId = null } = options;
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;
  const refreshRevision = useDashboardRefreshRevision();
  const resolvedTimeframeKey = timeframeKey(timeframe);
  const queryClient = useQueryClient();
  const reactQueryKey = useMemo(
    () => [
      'fleetMetrics',
      userKey,
      resolvedTimeframeKey,
      platform,
      scopedAccount?.platform ?? 'all',
      scopedAccount?.id ?? 'fleet',
      groupId ?? 'all',
      accountIds?.join(',') ?? null,
    ] as const,
    [userKey, resolvedTimeframeKey, platform, scopedAccount?.platform, scopedAccount?.id, groupId, accountIds],
  );
  const [state, setState] = useState<FleetMetricsState>(() => {
    const persisted = queryClient.getQueryData<FleetMetricsState>(reactQueryKey);
    if (persisted) {
      return {
        ...EMPTY_FLEET_METRICS_STATE,
        ...persisted,
        accounts: Array.isArray(persisted.accounts) ? persisted.accounts : [],
        series: Array.isArray(persisted.series) ? persisted.series : [],
        isLoading: false,
        hasError: false,
      };
    }

    const cached = cache.get(metricsCacheKey(userKey, resolvedTimeframeKey, platform, scopedAccount, accountIds, groupId));
    if (cached) {
      // Coerce array fields explicitly — spreading won't rescue an explicit
      // `accounts: undefined` stored in the cache by an older code path.
      return {
        ...EMPTY_FLEET_METRICS_STATE,
        ...cached,
        accounts: Array.isArray(cached.accounts) ? cached.accounts : [],
        series: Array.isArray(cached.series) ? cached.series : [],
        isLoading: false,
        hasError: false,
      };
    }
    return EMPTY_FLEET_METRICS_STATE;
  });

  useEffect(() => {
    void refreshRevision;
    let cancelled = false;

    if (!authUser) {
      // Stay in loading state while auth hydrates — flipping to zeroed KPIs
      // here flashes empty metrics on every mount.
      return;
    }

    if (!enabled) {
      // Caller is consuming pre-fetched metrics from a parent; do not re-fetch.
      return;
    }

    // SWR: re-check cache after userKey resolves so the warm payload renders
    // before the background fetch completes.
    const metricsKey = metricsCacheKey(userKey, resolvedTimeframeKey, platform, scopedAccount, accountIds, groupId);
    const persisted = queryClient.getQueryData<FleetMetricsState>(reactQueryKey);
    if (persisted) {
      setState({
        ...EMPTY_FLEET_METRICS_STATE,
        ...persisted,
        accounts: Array.isArray(persisted.accounts) ? persisted.accounts : [],
        series: Array.isArray(persisted.series) ? persisted.series : [],
        isLoading: false,
        hasError: false,
      });
    }

    const cached = cache.get(metricsKey);
    if (cached) setState({ ...cached, isLoading: false });

    // Freshness gate — skip the refetch if we just pulled this
    // (userKey, timeframe, platform) tuple under FRESH_MS ago.
    const persistedQueryState = queryClient.getQueryState(reactQueryKey);
    const persistedUpdatedAt = persistedQueryState?.dataUpdatedAt ?? 0;
    if (
      persistedUpdatedAt > 0 &&
      !persistedQueryState?.isInvalidated &&
      Date.now() - persistedUpdatedAt < DEFAULT_FRESH_MS
    ) return;
    if (cache.isFresh(metricsKey)) return;

    void queryClient.fetchQuery<FleetMetricsState>({
      queryKey: reactQueryKey,
      staleTime: DEFAULT_FRESH_MS,
      queryFn: async () => {
      const currentUserId = authUser.id;

      const days = Number.parseInt(resolvedTimeframeKey, 10) || 7;
      const now = new Date();
      const windowStart = new Date(now.getTime() - days * 24 * 60 * 60 * 1000);
      const priorStart = new Date(now.getTime() - 2 * days * 24 * 60 * 60 * 1000);

      const priorStartDate = priorStart.toISOString().slice(0, 10);

      const accountMetaKey = ['fleetAccountMeta', currentUserId] as const;
      const accountMeta = await queryClient.fetchQuery<FleetAccountMetaPayload>({
        queryKey: accountMetaKey,
        staleTime: 5 * 60_000,
        queryFn: async () => {
          const [threadsAcctRes, igAcctRes] = await Promise.all([
            supabase
              .from('accounts')
              .select('id, username, group_id, followers_count')
              .eq('user_id', currentUserId)
              .eq('is_active', true)
              .eq('is_retired', false),
            supabase
              .from('instagram_accounts')
              .select('id, username, group_id, follower_count')
              .eq('user_id', currentUserId)
              .eq('is_active', true),
          ]);
          if (threadsAcctRes.error) throw new Error(threadsAcctRes.error.message ?? JSON.stringify(threadsAcctRes.error));
          if (igAcctRes.error) throw new Error(igAcctRes.error.message ?? JSON.stringify(igAcctRes.error));
          return {
            threadsAcct: (threadsAcctRes.data ?? []) as AccountRow[],
            igAcct: (igAcctRes.data ?? []) as AccountRow[],
          };
        },
      });

      const threadsAcct = accountMeta.threadsAcct;
      const igAcct = accountMeta.igAcct;

      // Resolve which account IDs belong to this user — filter history table by ownership.
      const ownedThreadIds = new Set(threadsAcct.map((r) => r.id));
      const ownedIgIds = new Set(igAcct.map((r) => r.id));

      const platformFilter = (p: string | null) => {
        if (platform === 'all') return true;
        return p === platform;
      };
      const selectionIncludesAccount = (id: string, plat: 'threads' | 'instagram') => {
        if (!platformFilter(plat)) return false;
        if (scopedAccount) {
          return scopedAccount.platform === plat && scopedAccount.id === id;
        }
        if (accountIds && accountIds.length > 0) return accountIds.includes(id);
        return true;
      };
      const scopedHistoryAccountIds = [
        ...threadsAcct
          .filter((row) => selectionIncludesAccount(row.id, 'threads'))
          .map((row) => row.id),
        ...igAcct
          .filter((row) => selectionIncludesAccount(row.id, 'instagram'))
          .map((row) => row.id),
      ];

      const rawMetricsKey = ['fleetMetricsRaw', currentUserId, resolvedTimeframeKey] as const;
      const rawRequestKey = `${currentUserId}:${resolvedTimeframeKey}:${refreshRevision}`;
      const historyKey = [
        'fleetMetricsHistory',
        currentUserId,
        resolvedTimeframeKey,
        platform,
        scopedAccount?.platform ?? 'all',
        scopedAccount?.id ?? 'fleet',
        groupId ?? 'all',
        accountIds?.join(',') ?? null,
      ] as const;

      const [
        rpcData,
        historyPayload,
      ] = await withAnalyticsQueryTimeout(Promise.all([
        queryClient.fetchQuery<FleetMetricsRpcResponse>({
          queryKey: rawMetricsKey,
          staleTime: DEFAULT_FRESH_MS,
          queryFn: () => fetchFleetMetricsRpc(
            rawRequestKey,
            currentUserId,
            priorStart.toISOString(),
            now.toISOString(),
          ),
        }),
        queryClient.fetchQuery<FleetHistoryPayload>({
          queryKey: historyKey,
          staleTime: DEFAULT_FRESH_MS,
          queryFn: async () => {
            if (scopedHistoryAccountIds.length === 0) {
              return { history: [], historySeed: [] };
            }
            const historyBatches = chunkAccountIds(scopedHistoryAccountIds);
            const [historyResults, historySeedResults] = await Promise.all([
              Promise.all(historyBatches.map((ids) =>
                supabase
                  .from('account_metrics_history')
                  .select('account_id, platform, date, followers_count')
                  .in('account_id', ids)
                  .gte('date', priorStartDate)
                  .lte('date', now.toISOString().slice(0, 10))
                  .order('date', { ascending: true })
                  .limit(10000),
              )),
              Promise.all(historyBatches.map((ids) =>
                supabase
                  .from('account_metrics_history')
                  .select('account_id, platform, date, followers_count')
                  .in('account_id', ids)
                  .lt('date', priorStartDate)
                  .gte('date', new Date(priorStart.getTime() - 30 * 86_400_000).toISOString().slice(0, 10))
                  .order('date', { ascending: false })
                  .limit(10000),
              )),
            ]);
            const historyError = historyResults.find((result) => result.error)?.error;
            if (historyError) throw new Error(historyError.message ?? JSON.stringify(historyError));
            const historySeedError = historySeedResults.find((result) => result.error)?.error;
            if (historySeedError) throw new Error(historySeedError.message ?? JSON.stringify(historySeedError));
            return {
              history: historyResults.flatMap((result) => result.data ?? []),
              historySeed: historySeedResults.flatMap((result) => result.data ?? []),
            };
          },
        }),
      ]), 'fleet metrics');

      const allPublished = Array.isArray(rpcData.published) ? rpcData.published : [];
      const allFailed = Array.isArray(rpcData.failed) ? rpcData.failed : [];

      // For RPC buckets, account_key + platform tell us ownership directly.
      const isOwnedBucket = (b: { account_key: string; platform: string }) => {
        if (b.platform === 'threads') return ownedThreadIds.has(b.account_key);
        if (b.platform === 'instagram') return ownedIgIds.has(b.account_key);
        return false;
      };
      const scopedBucketFilter = (b: { account_key: string; platform: string }) => {
        if (!scopedAccount) return true;
        return b.platform === scopedAccount.platform && b.account_key === scopedAccount.id;
      };
      const groupBucketFilter = (b: { account_key: string }) => {
        if (scopedAccount || !accountIds || accountIds.length === 0) return true;
        return accountIds.includes(b.account_key);
      };

      // Partition published buckets into current + prior window by bucket_date.
      const windowStartDate = windowStart.toISOString().slice(0, 10);

      const current: PublishedBucket[] = [];
      const prior: PublishedBucket[] = [];
      for (const b of allPublished) {
        if (
          !platformFilter(b.platform)
          || !isOwnedBucket(b)
          || !scopedBucketFilter(b)
          || !groupBucketFilter(b)
        ) continue;
        if (b.bucket_date >= windowStartDate) current.push(b);
        else prior.push(b);
      }

      // Failed — for compliance.
      let failedCurrent = 0;
      let failedPrior = 0;
      for (const f of allFailed) {
        if (
          !platformFilter(f.platform)
          || !isOwnedBucket(f)
          || !scopedBucketFilter(f)
          || !groupBucketFilter(f)
        ) continue;
        if (f.bucket_date >= windowStartDate) failedCurrent += Number(f.failed_count) || 0;
        else failedPrior += Number(f.failed_count) || 0;
      }

      // EQS + aggregates for current window.
      // bucketToEqsSignals returns PostSignals built from the eqs_* fields,
      // which already reflect the per-post reach >= 50 filter applied SQL-side.
      const currentEqsSignals = current.map(bucketToEqsSignals);
      const priorEqsSignals = prior.map(bucketToEqsSignals);
      const eqs = eqsForSignals(currentEqsSignals);
      const priorEqs = eqsForSignals(priorEqsSignals);

      // totalReach + sendsPlusSaves use UNFILTERED totals to match the legacy
      // per-post .reduce that sums every post regardless of reach.
      const totalReach = current.reduce((sum, b) => sum + (Number(b.total_reach) || 0), 0);
      const priorReach = prior.reduce((sum, b) => sum + (Number(b.total_reach) || 0), 0);
      const reachDeltaPct = pctDelta(totalReach, priorReach);

      const priorEqsReach = priorEqsSignals.reduce((sum, s) => sum + s.reach, 0);
      const eqsDelta =
        prior.length === 0 || priorEqsReach <= 0
          ? null
          : Math.round((eqs - priorEqs) * 10) / 10;

      const sendsPlusSaves = current.reduce(
        (sum, b) => sum + (Number(b.total_sends) || 0) + (Number(b.total_saves) || 0),
        0,
      );
      const priorSendsPlusSaves = prior.reduce(
        (sum, b) => sum + (Number(b.total_sends) || 0) + (Number(b.total_saves) || 0),
        0,
      );
      const sendsPlusSavesDeltaPct = pctDelta(sendsPlusSaves, priorSendsPlusSaves);

      const publishedCurrent = current.reduce((sum, b) => sum + (Number(b.total_posts) || 0), 0);
      const publishedPrior = prior.reduce((sum, b) => sum + (Number(b.total_posts) || 0), 0);
      // Number of posts in the current window that cleared the EQS reach
      // floor. Drives the audit gate downstream — distinct from postCount,
      // which counts everything published. Optional on the bucket payload
      // so v5-or-older RPCs read as 0 without throwing.
      const eqsQualifyingPostCount = current.reduce(
        (sum, b) => sum + (Number(b.eqs_post_count) || 0),
        0,
      );
      const totalAttemptsCurrent = publishedCurrent + failedCurrent;
      const totalAttemptsPrior = publishedPrior + failedPrior;
      const scheduleCompliance = totalAttemptsCurrent === 0
        ? null
        : Math.round((publishedCurrent / totalAttemptsCurrent) * 1000) / 10;
      const scheduleCompliancePrior = totalAttemptsPrior === 0
        ? null
        : (publishedPrior / totalAttemptsPrior) * 100;
      const scheduleComplianceDelta = scheduleCompliance === null || scheduleCompliancePrior === null
        ? null
        : Math.round((scheduleCompliance - scheduleCompliancePrior) * 10) / 10;

      // Daily EQS buckets for the sparkline — group current buckets by bucket_date.
      const byDay = new Map<string, PublishedBucket[]>();
      for (const b of current) {
        if (!byDay.has(b.bucket_date)) byDay.set(b.bucket_date, []);
        byDay.get(b.bucket_date)?.push(b);
      }
      const dateKeys = fillDateRange(windowStart, now);
      const series: FleetMetricsPoint[] = dateKeys.map((date) => {
        const dayBuckets = byDay.get(date) ?? [];
        return {
          date,
          eqs: eqsForSignals(dayBuckets.map(bucketToEqsSignals)),
          reach: dayBuckets.reduce((sum, b) => sum + (Number(b.total_reach) || 0), 0),
        };
      });

      // Per-account aggregates — for Top/Underperforming leaderboards.
      const acctThreads = new Map(threadsAcct.map((r) => [r.id, r]));
      const acctIg = new Map(igAcct.map((r) => [r.id, r]));
      const acctAgg = new Map<string, FleetAccountAggregate>();

      const getOrCreate = (
        accountId: string,
        plat: 'threads' | 'instagram',
      ): FleetAccountAggregate => {
        const existing = acctAgg.get(accountId);
        if (existing) return existing;
        const meta = plat === 'threads' ? acctThreads.get(accountId) : acctIg.get(accountId);
        const created: FleetAccountAggregate = {
          accountId,
          platform: plat,
          username: meta?.username ?? null,
          groupId: meta?.group_id ?? null,
          eqs: 0,
          reach: 0,
          sends: 0,
          saves: 0,
          comments: 0,
          likes: 0,
          posts: 0,
          priorReach: 0,
          priorPosts: 0,
          reachDeltaPct: null,
          followerGrowthPct: null,
        };
        acctAgg.set(accountId, created);
        return created;
      };

      // Roll up current buckets per account.
      const eqsBucketsByAcct = new Map<string, PublishedBucket[]>();
      for (const b of current) {
        const plat: 'threads' | 'instagram' = b.platform === 'instagram' ? 'instagram' : 'threads';
        const agg = getOrCreate(b.account_key, plat);
        agg.reach += Number(b.total_reach) || 0;
        agg.sends += Number(b.total_sends) || 0;
        agg.saves += Number(b.total_saves) || 0;
        agg.comments += Number(b.total_comments) || 0;
        agg.likes += Number(b.total_likes) || 0;
        agg.posts += Number(b.total_posts) || 0;
        if (!eqsBucketsByAcct.has(b.account_key)) eqsBucketsByAcct.set(b.account_key, []);
        eqsBucketsByAcct.get(b.account_key)?.push(b);
      }
      for (const [accountId, buckets] of eqsBucketsByAcct) {
        const agg = acctAgg.get(accountId);
        if (agg) agg.eqs = eqsForSignals(buckets.map(bucketToEqsSignals));
      }

      // Per-account prior-window aggregation — reach + posts only.
      for (const b of prior) {
        const plat: 'threads' | 'instagram' = b.platform === 'instagram' ? 'instagram' : 'threads';
        const agg = getOrCreate(b.account_key, plat);
        agg.priorReach += Number(b.total_reach) || 0;
        agg.priorPosts += Number(b.total_posts) || 0;
      }
      for (const agg of acctAgg.values()) {
        agg.reachDeltaPct =
          agg.priorReach >= 10
            ? Math.round(((agg.reach - agg.priorReach) / agg.priorReach) * 1000) / 10
            : null;
      }

      // Follower growth % — use account_metrics_history where possible, fall back to null.
      // Filter history rows to owned accounts + selected platform.
      type HistRow = { account_id: string; platform: string; date: string; followers_count: number | null };
      const history = historyPayload.history as HistRow[];
      const historySeed = historyPayload.historySeed as HistRow[];
      const isOwnedScopedHistoryRow = (h: HistRow) => {
        if (!platformFilter(h.platform)) return false;
        if (scopedAccount) {
          if (scopedAccount.platform !== h.platform) return false;
          if (scopedAccount.id !== h.account_id) return false;
        }
        if (!scopedAccount && accountIds && accountIds.length > 0 && !accountIds.includes(h.account_id)) {
          return false;
        }
        if (h.platform === 'threads') return ownedThreadIds.has(h.account_id);
        if (h.platform === 'instagram') return ownedIgIds.has(h.account_id);
        return false;
      };

      const latestSeedByAccount = new Map<string, HistRow>();
      for (const row of historySeed) {
        if (!isOwnedScopedHistoryRow(row)) continue;
        if (row.followers_count == null) continue;
        if (!latestSeedByAccount.has(row.account_id)) {
          latestSeedByAccount.set(row.account_id, row);
        }
      }

      const scopedHistory = [
        ...Array.from(latestSeedByAccount.values()).sort((a, b) => a.date.localeCompare(b.date)),
        ...history.filter(isOwnedScopedHistoryRow),
      ];

      // Per-account follower growth — walk scopedHistory once, keeping the
      // latest followers_count on-or-before windowStart and on-or-before now
      // per account. Same shape as the fleet-wide sumOnOrBefore below.
      {
        const cutoffNowDate = now.toISOString().slice(0, 10);
        const cutoffStartDate = windowStart.toISOString().slice(0, 10);
        const latestNow = new Map<string, number>();
        const latestStart = new Map<string, number>();
        for (const row of scopedHistory) {
          if (row.followers_count == null) continue;
          if (row.date <= cutoffNowDate) latestNow.set(row.account_id, row.followers_count);
          if (row.date <= cutoffStartDate) latestStart.set(row.account_id, row.followers_count);
        }
        for (const agg of acctAgg.values()) {
          const endVal = latestNow.get(agg.accountId);
          const startVal = latestStart.get(agg.accountId);
          if (endVal == null || startVal == null || startVal <= 0) continue;
          agg.followerGrowthPct = Math.round(((endVal - startVal) / startVal) * 1000) / 10;
        }
      }

      const accounts = Array.from(acctAgg.values()).sort((a, b) => b.eqs - a.eqs);

      const sumOnOrBefore = (cutoffIso: string): number | null => {
        // For each owned account in scope, pick the latest followers_count on-or-before cutoff.
        const perAcct = new Map<string, number>();
        const cutoffDate = cutoffIso.slice(0, 10);
        for (const row of scopedHistory) {
          if (row.date > cutoffDate) continue;
          if (row.followers_count == null) continue;
          // scopedHistory is sorted ascending; later rows override earlier — ends on the latest valid.
          perAcct.set(row.account_id, row.followers_count);
        }
        if (perAcct.size === 0) return null;
        let total = 0;
        for (const v of perAcct.values()) total += v;
        return total;
      };

      const followersNow = sumOnOrBefore(now.toISOString());
      const followersWindowStart = sumOnOrBefore(windowStart.toISOString());
      const followersPriorStart = sumOnOrBefore(priorStart.toISOString());

      const followerGrowthPct = followersWindowStart && followersWindowStart > 0 && followersNow != null
        ? Math.round(((followersNow - followersWindowStart) / followersWindowStart) * 1000) / 10
        : null;
      const followerGrowthPriorPct = followersPriorStart && followersPriorStart > 0 && followersWindowStart != null
        ? ((followersWindowStart - followersPriorStart) / followersPriorStart) * 100
        : null;
      const followerGrowthDeltaPct = followerGrowthPct != null && followerGrowthPriorPct != null
        ? Math.round((followerGrowthPct - followerGrowthPriorPct) * 10) / 10
        : null;

      const next: FleetMetricsState = {
        eqs,
        eqsDelta,
        totalReach,
        reachDeltaPct,
        sendsPlusSaves,
        sendsPlusSavesDeltaPct,
        scheduleCompliance,
        scheduleComplianceDelta,
        followerGrowthPct,
        followerGrowthDeltaPct,
        series,
        accounts,
        postCount: publishedCurrent,
        eqsQualifyingPostCount,
        isLoading: false,
        hasError: false,
      };
      cache.set(metricsKey, next);
      return next;
      },
    }).then((next) => {
      if (!cancelled) setState(next);
    }).catch((err) => {
      // Silent failures here drove every consumer (HeroTile, FleetAnomaly,
      // InsightsRail, ribbon …) to render stale-or-zero data with no
      // signal. Log to Sentry so we can see failure rate, and flip
      // isLoading off so callers stop spinning forever. State retains the
      // last cached payload (which was set above when cache was warm).
      if (!cancelled) {
        // Lazy import to avoid pulling Sentry into the hook's eager bundle.
        void import('@/lib/sentry').then(({ captureException }) => {
          captureException(err instanceof Error ? err : new Error(String(err)), {
            hook: { name: 'useFleetMetrics', timeframe: resolvedTimeframeKey, platform },
          });
        }).catch(() => { /* sentry import failure is non-fatal */ });
        setState((prev) => {
          const hasUsablePayload =
            prev.postCount > 0 ||
            prev.accounts.length > 0 ||
            prev.series.length > 0 ||
            prev.totalReach > 0 ||
            prev.sendsPlusSaves > 0 ||
            prev.scheduleCompliance != null ||
            prev.followerGrowthPct != null;
          return { ...prev, isLoading: false, hasError: !hasUsablePayload };
        });
      }
    });

    return () => { cancelled = true; };
  }, [
    userKey,
    resolvedTimeframeKey,
    platform,
    authUser,
    scopedAccount,
    accountIds,
    groupId,
    enabled,
    refreshRevision,
    queryClient,
    reactQueryKey,
  ]);

  return state;
}
