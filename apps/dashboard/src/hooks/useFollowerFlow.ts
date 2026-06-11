// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';
import type { FleetMetricsPlatform } from '@/hooks/useFleetMetrics';
import { withAnalyticsQueryTimeout } from '@/lib/analyticsQueryTimeout';
import { chunkAccountIds } from '@/lib/accountIdBatching';

export interface FollowerFlowState {
  gains: number[];
  losses: number[];
  netTotal: string;
  inflowTotal: string;
  outflowTotal: string;
  churnRate: string;
  windowLabel: string;
  hasRealData: boolean;
  loading: boolean;
}

const MIN_SNAPSHOTS = 4;

const EMPTY: Omit<FollowerFlowState, 'loading'> = {
  gains: [],
  losses: [],
  netTotal: '—',
  inflowTotal: '—',
  outflowTotal: '—',
  churnRate: '—',
  windowLabel: '—',
  hasRealData: false,
};

function windowLabel(days: number): string {
  return `${Math.max(1, Math.round(days))} days`;
}

function formatNet(n: number): string {
  return `${n >= 0 ? '+' : ''}${n.toLocaleString()}`;
}

export interface FollowerFlowAccountScope {
  accountId: string;
  accountPlatform: 'threads' | 'instagram';
  accountHandle?: string | null | undefined;
}

export function useFollowerFlow(
  platform: FleetMetricsPlatform,
  timeframeDays: number,
  accountScope?: FollowerFlowAccountScope | null,
  scopedAccountIds?: string[],
): FollowerFlowState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending } = useQuery({
    queryKey: [
      'followerFlow',
      userKey,
      platform,
      timeframeDays,
      accountScope?.accountId ?? null,
      accountScope?.accountPlatform ?? null,
      accountScope?.accountHandle ?? null,
      scopedAccountIds?.join(',') ?? null,
    ],
    enabled: !!userKey,
    staleTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
    retry: false,
    queryFn: () => withAnalyticsQueryTimeout((async () => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return EMPTY;

      let accountIds: string[] = [];
      const resolveLegacyInstagramAccountId = async () => {
        const username = accountScope?.accountHandle?.replace(/^@/, '') ?? null;
        if (!username) return null;
        const { data: resolvedAccount, error: resolvedError } = await supabase
          .from('instagram_accounts')
          .select('id')
          .eq('user_id', user.id)
          .eq('is_active', true)
          .eq('username', username)
          .maybeSingle();

        if (resolvedError) throw resolvedError;
        return resolvedAccount?.id ?? null;
      };

      if (accountScope?.accountId) {
        accountIds = [accountScope.accountId];
      } else if (scopedAccountIds && scopedAccountIds.length > 0) {
        accountIds = scopedAccountIds;
      } else {
        if (platform === 'instagram') {
          const { data: igAccounts, error } = await supabase
            .from('instagram_accounts')
            .select('id')
            .eq('user_id', user.id)
            .eq('is_active', true);
          if (error) throw error;
          accountIds = (igAccounts ?? []).map((a) => a.id);
        } else if (platform === 'threads') {
          const { data: threadAccounts, error } = await supabase
            .from('accounts')
            .select('id')
            .eq('user_id', user.id)
            .eq('is_active', true)
            .eq('is_retired', false);
          if (error) throw error;
          accountIds = (threadAccounts ?? []).map((a) => a.id);
        } else {
          const [threadAccountsRes, igAccountsRes] = await Promise.all([
            supabase
              .from('accounts')
              .select('id')
              .eq('user_id', user.id)
              .eq('is_active', true)
              .eq('is_retired', false),
            supabase
              .from('instagram_accounts')
              .select('id')
              .eq('user_id', user.id)
              .eq('is_active', true),
          ]);
          if (threadAccountsRes.error) throw threadAccountsRes.error;
          if (igAccountsRes.error) throw igAccountsRes.error;
          accountIds = [
            ...(threadAccountsRes.data ?? []).map((a) => a.id),
            ...(igAccountsRes.data ?? []).map((a) => a.id),
          ];
        }
        if (accountIds.length === 0) return EMPTY;
      }

      const since = new Date();
      since.setDate(since.getDate() - timeframeDays - 1);
      since.setHours(0, 0, 0, 0);
      const sinceStr = since.toISOString().split('T')[0]!;

      type SnapshotRow = {
        account_id: string;
        date: string;
        followers_count: number | null;
      };

      const fetchSnapshotsFor = async (ids: string[]) => {
        const batches = chunkAccountIds(ids);
        const [snapshotResults, seedSnapshotResults] = await Promise.all([
          Promise.all(batches.map((batchIds) =>
            supabase
              .from('account_analytics')
              .select('account_id, date, followers_count')
              .in('account_id', batchIds)
              .not('followers_count', 'is', null)
              .gte('date', sinceStr)
              .order('date', { ascending: true }),
          )),
          Promise.all(batches.map((batchIds) =>
            supabase
              .from('account_analytics')
              .select('account_id, date, followers_count')
              .in('account_id', batchIds)
              .not('followers_count', 'is', null)
              .lte('date', sinceStr)
              .order('date', { ascending: false }),
          )),
        ]);

        const snapshotsError = snapshotResults.find((result) => result.error)?.error;
        if (snapshotsError) throw snapshotsError;
        const seedSnapshotsError = seedSnapshotResults.find((result) => result.error)?.error;
        if (seedSnapshotsError) throw seedSnapshotsError;

        return {
          snapshots: snapshotResults.flatMap((result) => (result.data ?? []) as SnapshotRow[]),
          seedSnapshots: seedSnapshotResults.flatMap((result) => (result.data ?? []) as SnapshotRow[]),
        };
      };

      let { snapshots, seedSnapshots } = await fetchSnapshotsFor(accountIds);
      if (
        accountScope?.accountPlatform === 'instagram' &&
        snapshots.length < MIN_SNAPSHOTS
      ) {
        const legacyAccountId = await resolveLegacyInstagramAccountId();
        if (legacyAccountId && legacyAccountId !== accountScope.accountId) {
          ({ snapshots, seedSnapshots } = await fetchSnapshotsFor([legacyAccountId]));
        }
      }

      if (snapshots.length < MIN_SNAPSHOTS) return EMPTY;

      const latestSeedByAccount = new Map<string, number>();
      for (const snap of seedSnapshots) {
        if (!latestSeedByAccount.has(snap.account_id)) {
          latestSeedByAccount.set(snap.account_id, snap.followers_count ?? 0);
        }
      }

      const snapshotsByDate = new Map<string, Map<string, number>>();
      for (const snap of snapshots) {
        const byAccount = snapshotsByDate.get(snap.date) ?? new Map<string, number>();
        byAccount.set(snap.account_id, snap.followers_count ?? 0);
        snapshotsByDate.set(snap.date, byAccount);
      }

      const dates = Array.from(snapshotsByDate.keys()).sort();
      if (dates.length < 2) return EMPTY;

      const currentFollowers = new Map(latestSeedByAccount);
      const totalsByDate: Array<{ date: string; total: number }> = [];

      for (const date of dates) {
        const updates = snapshotsByDate.get(date);
        if (updates) {
          for (const [accountId, followers] of updates) {
            currentFollowers.set(accountId, followers);
          }
        }

        if (currentFollowers.size === 0) continue;
        let total = 0;
        for (const followers of currentFollowers.values()) {
          total += followers;
        }
        totalsByDate.push({ date, total });
      }

      if (totalsByDate.length < 2) return EMPTY;

      const gains: number[] = [];
      const losses: number[] = [];
      let totalGains = 0;
      let totalLosses = 0;

      for (let i = 1; i < totalsByDate.length; i++) {
        const delta = totalsByDate[i]!.total - totalsByDate[i - 1]!.total;
        if (delta >= 0) {
          gains.push(delta);
          losses.push(0);
          totalGains += delta;
        } else {
          gains.push(0);
          losses.push(Math.abs(delta));
          totalLosses += Math.abs(delta);
        }
      }

      if (gains.length === 0) return EMPTY;

      const net = totalGains - totalLosses;
      const baseFollowers = Math.max(totalsByDate[0]!.total, 1);
      const churn = `${((totalLosses / baseFollowers) * 100).toFixed(1)}%`;

      return {
        gains,
        losses,
        netTotal: formatNet(net),
        inflowTotal: totalGains.toLocaleString(),
        outflowTotal: totalLosses.toLocaleString(),
        churnRate: churn,
        windowLabel: windowLabel(timeframeDays),
        hasRealData: true,
      };
    })(), 'follower flow'),
  });

  return {
    ...(data ?? EMPTY),
    loading: !!userKey && isPending,
  };
}
