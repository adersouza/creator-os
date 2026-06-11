import { useEffect, useState } from 'react';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';
import { createHookCache, DEFAULT_FRESH_MS } from '@/hooks/_hookCache';
import { fetchConnectedAccounts } from '@/hooks/useConnectedAccounts';
import { useDashboardRefreshRevision } from '@/lib/dashboardRefreshSignal';
import { queryClient } from '@/lib/queryClient';
import { queryKeys } from '@/lib/queryKeys';
import { toDays, toLabel, type TimeRangeInput } from '@/lib/timeRange';
import type { AccountScopeValue } from '@/stores/useAccountScopeStore';

/**
 * Top posts by sends + saves across the selected window — powers the mobile
 * Analytics "Posts" view. Published posts only; ranks by the discovery-
 * weighted metric Mosseri highlights (IG sends + saves, Threads reposts +
 * replies). Returns at most 30 rows, scoped to the selected platform.
 */

export type TopPostsTimeframe = TimeRangeInput;
export type TopPostsPlatform = 'all' | 'threads' | 'ig';
const UNASSIGNED_COLOR = '#6B6B70';

export interface TopPostRow {
  id: string;
  platform: 'threads' | 'instagram';
  caption: string;
  mediaUrl: string | null;
  accountId: string | null;
  accountHandle: string;
  groupId: string | null;
  groupName: string;
  groupColor: string;
  reach: number;
  sends: number;
  saves: number;
  likes: number;
  comments: number;
  publishedAt: string;
}

interface State {
  posts: TopPostRow[];
  isLoading: boolean;
  hasError: boolean;
}

const TOP_POST_SAMPLE_LIMIT = 5000;
const cache = createHookCache<Record<string, State>>();
const inFlight = new Map<string, Promise<State>>();
type RawTopPostRow = {
  id: string | number;
  platform: string | null;
  content: string | null;
  media_urls: unknown;
  account_id: string | null;
  instagram_account_id: string | null;
  published_at: string | null;
  created_at: string | null;
  likes_count: number | null;
  shares_count: number | null;
  replies_count: number | null;
  views_count: number | null;
  ig_views: number | null;
  ig_saved: number | null;
  ig_shares: number | null;
  ig_comment_count: number | null;
  ig_reach: number | null;
};
// Per-combo freshness — the cache is keyed by userKey (bucket of combos), so
// its own updatedAt isn't granular enough. Track each (timeframe, platform)
// combo independently so switching filters still fetches.
const lastFetchedAt = new Map<string, number>();

export function resetTopPostsCache() {
  cache.clearAll();
  inFlight.clear();
  lastFetchedAt.clear();
}

function mapRow(
  // biome-ignore lint/suspicious/noExplicitAny: row shape varies per platform
  row: any,
  meta: { handle: string; groupId: string | null; groupName: string; groupColor: string },
): TopPostRow {
  const isIg = row.platform === 'instagram';
  const igDistributionMetric = firstPositive(row.ig_reach, row.ig_views, row.views_count);
  return {
    id: String(row.id),
    platform: isIg ? 'instagram' : 'threads',
    caption: typeof row.content === 'string' ? row.content : '',
    mediaUrl: Array.isArray(row.media_urls) && row.media_urls.length ? String(row.media_urls[0]) : null,
    accountId: isIg ? row.instagram_account_id ?? null : row.account_id ?? null,
    accountHandle: meta.handle,
    groupId: meta.groupId,
    groupName: meta.groupName,
    groupColor: meta.groupColor,
    reach: isIg ? igDistributionMetric : row.views_count ?? 0,
    sends: isIg ? row.ig_shares ?? 0 : row.shares_count ?? 0,
    saves: isIg ? row.ig_saved ?? 0 : 0,
    likes: row.likes_count ?? 0,
    comments: isIg ? row.ig_comment_count ?? 0 : row.replies_count ?? 0,
    publishedAt: String(row.published_at ?? row.created_at ?? ''),
  };
}

export function firstPositive(...values: Array<number | null | undefined>): number {
  return values.find((value) => typeof value === 'number' && value > 0) ?? 0;
}

export function useTopPosts(
  timeframe: TopPostsTimeframe,
  platform: TopPostsPlatform,
  scopedAccount: AccountScopeValue | null = null,
  accountIds?: string[],
  groupId?: string | null,
): State {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;
  const refreshRevision = useDashboardRefreshRevision();
  const timeframeLabel = toLabel(typeof timeframe === 'number' ? { days: timeframe } : timeframe);
  const timeframeDays = toDays(timeframe);
  const cacheKey = `${userKey ?? 'anon'}:${timeframeLabel}:${platform}:${scopedAccount?.platform ?? 'all'}:${scopedAccount?.id ?? 'fleet'}:${groupId ?? 'all'}:${accountIds?.join(',') ?? 'fleet'}`;
  const [state, setState] = useState<State>(() => {
    const all = cache.get(userKey);
    const cached = all?.[cacheKey];
    if (cached) return { ...cached, isLoading: false, hasError: false };
    return { posts: [], isLoading: true, hasError: false };
  });

  useEffect(() => {
    void refreshRevision;
    let cancelled = false;
    if (!authUser) {
      // Stay loading while auth hydrates.
      return;
    }

    const all = cache.get(userKey);
    const cached = all?.[cacheKey];
    if (cached) setState({ ...cached, isLoading: false, hasError: false });

    // Freshness gate (per-combo).
    const fetchedAt = lastFetchedAt.get(cacheKey);
    if (fetchedAt !== undefined && Date.now() - fetchedAt < DEFAULT_FRESH_MS) return;

    const existing = inFlight.get(cacheKey);
    if (existing) {
      existing
        .then((next) => {
          if (!cancelled) setState(next);
        })
        .catch(() => {
          if (!cancelled) {
            setState((prev) => ({
              ...prev,
              isLoading: false,
              hasError: prev.posts.length === 0,
            }));
          }
        });
      return () => {
        cancelled = true;
      };
    }

    const request = (async (): Promise<State> => {
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user) return { posts: [], isLoading: false, hasError: false };

      const since = new Date(Date.now() - timeframeDays * 24 * 60 * 60 * 1000).toISOString();

      const [rawPosts, connectedAccounts] = await Promise.all([
        queryClient.fetchQuery<RawTopPostRow[]>({
          queryKey: ['topPostsRaw', user.id, timeframeLabel],
          staleTime: DEFAULT_FRESH_MS,
          gcTime: 15 * 60_000,
          queryFn: async () => {
            const { data, error } = await supabase
              .from('posts')
              .select(
                  'id, platform, content, media_urls, account_id, instagram_account_id, published_at, created_at, ' +
                  'likes_count, shares_count, replies_count, views_count, ig_views, ig_saved, ig_shares, ig_comment_count, ig_reach',
              )
              .eq('user_id', user.id)
              .eq('status', 'published')
              .gte('published_at', since)
              .order('published_at', { ascending: false })
              .limit(TOP_POST_SAMPLE_LIMIT);
            if (error) throw error;
            return (data ?? []) as unknown as RawTopPostRow[];
          },
        }),
        queryClient.fetchQuery({
          queryKey: queryKeys.accounts.connected(user.id),
          staleTime: 5 * 60_000,
          gcTime: 15 * 60_000,
          queryFn: () => fetchConnectedAccounts(user.id),
        }),
      ]);

      const metaById = new Map<string, { handle: string; groupId: string | null; groupName: string; groupColor: string }>();
      for (const account of connectedAccounts) {
        metaById.set(account.id, {
          handle: account.handle.replace(/^@/, ''),
          groupId: account.groupId,
          groupName: account.groupName,
          groupColor: account.groupColor,
        });
      }

      const rows = rawPosts.filter((row) => {
        if (platform !== 'all' && row.platform !== (platform === 'ig' ? 'instagram' : 'threads')) return false;
        if (scopedAccount?.platform === 'threads') {
          return row.platform === 'threads' && row.account_id === scopedAccount.id;
        }
        if (scopedAccount?.platform === 'instagram') {
          return row.platform === 'instagram' && row.instagram_account_id === scopedAccount.id;
        }
        if (accountIds && accountIds.length > 0) {
          const rowAccountId = row.platform === 'instagram' ? row.instagram_account_id : row.account_id;
          return !!rowAccountId && accountIds.includes(rowAccountId);
        }
        return true;
      }).map((row) => {
        const isIg = row.platform === 'instagram';
        const accountId = isIg ? row.instagram_account_id : row.account_id;
        const meta = accountId
          ? metaById.get(accountId) ?? { handle: 'unknown', groupId: null, groupName: 'Unassigned', groupColor: UNASSIGNED_COLOR }
          : { handle: 'unknown', groupId: null, groupName: 'Unassigned', groupColor: UNASSIGNED_COLOR };
        return mapRow(row, meta);
      });

      rows.sort((a, b) => b.sends + b.saves - (a.sends + a.saves));
      const top = rows.slice(0, 30);

      const next: State = { posts: top, isLoading: false, hasError: false };
      const prev = cache.get(userKey) ?? {};
      cache.set(userKey, { ...prev, [cacheKey]: next });
      lastFetchedAt.set(cacheKey, Date.now());
      return next;
    })();
    inFlight.set(cacheKey, request);
    request
      .then((next) => {
        if (!cancelled) setState(next);
      })
      .catch(() => {
        if (!cancelled) {
          setState((prev) => ({
            ...prev,
            isLoading: false,
            hasError: prev.posts.length === 0,
          }));
        }
      })
      .finally(() => {
        if (inFlight.get(cacheKey) === request) inFlight.delete(cacheKey);
      });

    return () => {
      cancelled = true;
    };
  }, [userKey, timeframeDays, timeframeLabel, platform, cacheKey, authUser, scopedAccount, accountIds, refreshRevision]);

  return state;
}
