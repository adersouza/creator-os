// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';
import { fetchConnectedAccounts } from '@/hooks/useConnectedAccounts';
import { withAnalyticsQueryTimeout } from '@/lib/analyticsQueryTimeout';
import { queryClient } from '@/lib/queryClient';
import { queryKeys } from '@/lib/queryKeys';
import { toDays, toLabel, type TimeRangeInput } from '@/lib/timeRange';
import { chunkAccountIds } from '@/lib/accountIdBatching';

export interface NonFollowerReachState {
  nonFollowerPct: number;
  followerPct: number;
  delta: string | null;
  series: NonFollowerReachPoint[];
  hasRealData: boolean;
  loading: boolean;
}

export interface NonFollowerReachPoint {
  date: string;
  nonFollowerPct: number;
  reach: number;
}

export interface NonFollowerReachAccountScope {
  accountId: string;
  accountPlatform: 'threads' | 'instagram';
  accountHandle?: string | null | undefined;
}

const MIN_SAMPLES = 3;

const EMPTY: Omit<NonFollowerReachState, 'loading'> = {
  nonFollowerPct: 0,
  followerPct: 0,
  delta: null,
  series: [],
  hasRealData: false,
};

interface ReachShareRow {
  date: string;
  ig_non_follower_reach_pct: number | null;
  ig_reach: number | null;
  total_reach: number | null;
  total_views: number | null;
}

function averageNonFollowerPct(rows: ReachShareRow[]): number | null {
  if (rows.length === 0) return null;

  let weightedPct = 0;
  let weightedReach = 0;

  for (const row of rows) {
    const pct = row.ig_non_follower_reach_pct;
    if (pct == null) continue;

    const reach = row.ig_reach ?? row.total_reach ?? row.total_views ?? 0;
    if (reach > 0) {
      weightedPct += pct * reach;
      weightedReach += reach;
    }
  }

  if (weightedReach > 0) return weightedPct / weightedReach;
  return null;
}

function dateCutoff(daysAgo: number): string {
  const d = new Date();
  d.setDate(d.getDate() - daysAgo);
  d.setHours(0, 0, 0, 0);
  return d.toISOString().split('T')[0]!;
}

export function useNonFollowerReach(
  timeframe: TimeRangeInput,
  accountScope?: NonFollowerReachAccountScope | null,
  selectedAccountIds?: string[],
  groupId?: string | null,
): NonFollowerReachState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;
  const rangeForDays = typeof timeframe === 'number' ? { days: timeframe } : timeframe;
  const timeframeDays = toDays(rangeForDays);
  const timeframeLabel = toLabel(rangeForDays);

  const { data, isPending } = useQuery({
    queryKey: [
      'nonFollowerReach',
      userKey,
      timeframeLabel,
      accountScope?.accountId ?? null,
      accountScope?.accountPlatform ?? null,
      accountScope?.accountHandle ?? null,
      groupId ?? 'all',
      selectedAccountIds?.join(',') ?? null,
    ],
    enabled: !!userKey,
    staleTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
    retry: false,
    queryFn: () => withAnalyticsQueryTimeout((async () => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return EMPTY;
      const connectedAccounts = await queryClient.fetchQuery({
        queryKey: queryKeys.accounts.connected(user.id),
        staleTime: 5 * 60_000,
        gcTime: 15 * 60_000,
        queryFn: () => fetchConnectedAccounts(user.id),
      });

      let accountIds: string[] = [];
      const resolveLegacyInstagramAccountId = async () => {
        const username = accountScope?.accountHandle?.replace(/^@/, '') ?? null;
        if (!username) return null;
        const connected = connectedAccounts.find(
          (account) => account.platform === 'instagram' && account.handle.replace(/^@/, '') === username,
        );
        if (connected) return connected.id;

        const { data: resolvedAccount, error: resolvedError } = await supabase
          .from('accounts')
          .select('id')
          .eq('user_id', user.id)
          .eq('is_active', true)
          .eq('username', username)
          .maybeSingle();

        if (resolvedError) throw resolvedError;
        return resolvedAccount?.id ?? null;
      };

      if (accountScope?.accountId) {
        if (accountScope.accountPlatform !== 'instagram') return EMPTY;
        accountIds = [accountScope.accountId];
      } else if (selectedAccountIds && selectedAccountIds.length > 0) {
        const selected = new Set(selectedAccountIds);
        accountIds = connectedAccounts
          .filter((account) => account.platform === 'instagram' && selected.has(account.id))
          .map((account) => account.id);
        if (accountIds.length === 0) return EMPTY;
      } else {
        accountIds = connectedAccounts
          .filter((account) => account.platform === 'instagram')
          .map((account) => account.id);
        if (accountIds.length === 0) return EMPTY;
      }

      const cutoff = dateCutoff(timeframeDays);
      const priorCutoff = dateCutoff(timeframeDays * 2);

      const fetchReachRows = async (ids: string[]) => {
        const batches = chunkAccountIds(ids);
        const [currentResults, priorResults] = await Promise.all([
          Promise.all(batches.map((batchIds) =>
            supabase
              .from('account_analytics')
              .select('date, ig_non_follower_reach_pct, ig_reach, total_reach, total_views')
              .in('account_id', batchIds)
              .not('ig_non_follower_reach_pct', 'is', null)
              .gte('date', cutoff)
              .order('date', { ascending: true }),
          )),
          Promise.all(batches.map((batchIds) =>
            supabase
              .from('account_analytics')
              .select('date, ig_non_follower_reach_pct, ig_reach, total_reach, total_views')
              .in('account_id', batchIds)
              .not('ig_non_follower_reach_pct', 'is', null)
              .gte('date', priorCutoff)
              .lt('date', cutoff),
          )),
        ]);

        const currentError = currentResults.find((result) => result.error)?.error;
        if (currentError) throw currentError;
        const priorError = priorResults.find((result) => result.error)?.error;
        if (priorError) throw priorError;

        return {
          current: currentResults.flatMap((result) => (result.data ?? []) as ReachShareRow[]),
          prior: priorResults.flatMap((result) => (result.data ?? []) as ReachShareRow[]),
        };
      };

      let { current, prior } = await fetchReachRows(accountIds);
      if (
        accountScope?.accountPlatform === 'instagram' &&
        current.length < MIN_SAMPLES
      ) {
        const legacyAccountId = await resolveLegacyInstagramAccountId();
        if (legacyAccountId && legacyAccountId !== accountScope.accountId) {
          ({ current, prior } = await fetchReachRows([legacyAccountId]));
        }
      }

      if (current.length < MIN_SAMPLES) return EMPTY;

      const avgCurrent = averageNonFollowerPct(current);
      if (avgCurrent === null) return EMPTY;

      const avgPrior =
        prior.length >= 2
          ? averageNonFollowerPct(prior)
          : null;

      const nonFollowerPct = Math.round(avgCurrent * 10) / 10;
      const followerPct = Math.round((100 - avgCurrent) * 10) / 10;
      const deltaPp = avgPrior !== null ? avgCurrent - avgPrior : null;
      const delta =
        deltaPp !== null
          ? `${deltaPp >= 0 ? '+' : ''}${deltaPp.toFixed(1)}pp vs prior`
          : null;

      const byDate = new Map<string, ReachShareRow[]>();
      for (const row of current) {
        if (!byDate.has(row.date)) byDate.set(row.date, []);
        byDate.get(row.date)?.push(row);
      }

      const series = Array.from(byDate.entries())
        .map(([date, rows]) => {
          const dailyPct = averageNonFollowerPct(rows);
          const reach = rows.reduce(
            (sum, row) => sum + (row.ig_reach ?? row.total_reach ?? row.total_views ?? 0),
            0,
          );
          return dailyPct === null
            ? null
            : {
                date,
                nonFollowerPct: Math.round(dailyPct * 10) / 10,
                reach,
              };
        })
        .filter((point): point is NonFollowerReachPoint => point !== null);

      return { nonFollowerPct, followerPct, delta, series, hasRealData: true };
    })(), 'non-follower reach'),
  });

  return {
    ...(data ?? EMPTY),
    loading: !!userKey && isPending,
  };
}
