import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';
import { queryKeys } from '@/lib/queryKeys';
import type { AccountScopeValue } from '@/stores/useAccountScopeStore';

type ScopePlatform = 'all' | 'threads' | 'ig';
type ScopeTimeframe = '7' | '30' | '90';

export type AttentionSeverity = 'crit' | 'warn';
export type AttentionAction = 'Reconnect' | 'Post' | 'Review';

export interface AttentionItem {
  id: string;
  handle: string;
  platform: 'threads' | 'instagram';
  severity: AttentionSeverity;
  issue: string;
  action: AttentionAction;
}

interface State {
  items: AttentionItem[];
  totalCount: number;
  gapsCount: number;
  isLoading: boolean;
  hasError: boolean;
}

const MAX_ROWS = 5;
const DORMANT_HOURS_BY_TIMEFRAME: Record<ScopeTimeframe, number> = {
  '7': 72,
  '30': 168,
  '90': 336,
};
const GAP_WINDOW_HOURS_BY_TIMEFRAME: Record<ScopeTimeframe, number> = {
  '7': 48,
  '30': 96,
  '90': 168,
};

const EMPTY: Omit<State, 'isLoading' | 'hasError'> = { items: [], totalCount: 0, gapsCount: 0 };

type AcctRow = {
  id: string;
  username: string | null;
  needs_reauth: boolean | null;
  token_expires_at: string | null;
  last_synced_at: string | null;
};

/**
 * Surfaces accounts that need the operator's eye: expired tokens (critical),
 * dormant accounts with no recent sync (warning), plus a count of accounts
 * with empty queues over the next 48h for the gaps strip.
 */
export function useNeedsAttention(
  platform: ScopePlatform = 'all',
  timeframe: ScopeTimeframe = '7',
  scopedAccount: AccountScopeValue | null = null,
  accountIds?: string[],
  groupId?: string | null,
): State {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending, isError } = useQuery({
    queryKey: queryKeys.posts.needsAttention(
      userKey,
      platform,
      timeframe,
      scopedAccount?.id ?? null,
      scopedAccount?.platform ?? null,
      groupId ?? 'all',
      accountIds?.join(',') ?? null,
    ),
    enabled: !!userKey,
    queryFn: async () => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return EMPTY;

      const now = new Date();
      const dormantHours = DORMANT_HOURS_BY_TIMEFRAME[timeframe];
      const gapWindowHours = GAP_WINDOW_HOURS_BY_TIMEFRAME[timeframe];
      const dormantCutoff = new Date(now.getTime() - dormantHours * 60 * 60 * 1000).toISOString();

      const skipThreads = scopedAccount?.platform === 'instagram' || platform === 'ig';
      const skipInstagram = scopedAccount?.platform === 'threads' || platform === 'threads';

      const threadsPromise = skipThreads
        ? Promise.resolve({ data: [] as AcctRow[], error: null })
        : (() => {
            let q = supabase
              .from('accounts')
              .select('id, username, needs_reauth, token_expires_at, last_synced_at')
              .eq('user_id', user.id)
              .eq('is_active', true)
              .eq('is_retired', false);
            if (scopedAccount?.platform === 'threads') q = q.eq('id', scopedAccount.id);
            else if (accountIds && accountIds.length > 0) q = q.in('id', accountIds);
            return q;
          })();

      const instagramPromise = skipInstagram
        ? Promise.resolve({ data: [] as AcctRow[], error: null })
        : (() => {
            let q = supabase
              .from('instagram_accounts')
              .select('id, username, needs_reauth, token_expires_at, last_synced_at')
              .eq('user_id', user.id)
              .eq('is_active', true);
            if (scopedAccount?.platform === 'instagram') q = q.eq('id', scopedAccount.id);
            else if (accountIds && accountIds.length > 0) q = q.in('id', accountIds);
            return q;
          })();

      let scheduledQuery = supabase
        .from('posts')
        .select('account_id, instagram_account_id, platform')
        .eq('user_id', user.id)
        .eq('status', 'scheduled')
        .gte('scheduled_for', now.toISOString())
        .lt('scheduled_for', new Date(now.getTime() + gapWindowHours * 60 * 60 * 1000).toISOString());

      if (platform === 'threads') {
        scheduledQuery = scheduledQuery.eq('platform', 'threads');
      } else if (platform === 'ig') {
        scheduledQuery = scheduledQuery.eq('platform', 'instagram');
      }
      if (scopedAccount?.platform === 'threads') {
        scheduledQuery = scheduledQuery.eq('account_id', scopedAccount.id);
      } else if (scopedAccount?.platform === 'instagram') {
        scheduledQuery = scheduledQuery.eq('instagram_account_id', scopedAccount.id);
      } else if (accountIds && accountIds.length > 0) {
        scheduledQuery = scheduledQuery.or(
          `account_id.in.(${accountIds.join(',')}),instagram_account_id.in.(${accountIds.join(',')})`,
        );
      }

      const [threadsRes, igRes, scheduledRes] = await Promise.all([
        threadsPromise,
        instagramPromise,
        scheduledQuery,
      ]);

      if (threadsRes.error) throw threadsRes.error;
      if (igRes.error) throw igRes.error;
      if (scheduledRes.error) throw scheduledRes.error;

      const classify = (
        row: AcctRow,
        platform: 'threads' | 'instagram',
      ): AttentionItem | null => {
        const tokenDead = row.needs_reauth === true
          || (row.token_expires_at ? new Date(row.token_expires_at).getTime() < now.getTime() : false);
        if (tokenDead) {
          return {
            id: row.id,
            handle: row.username ? `@${row.username}` : 'Unnamed account',
            platform,
            severity: 'crit',
            issue: 'Token expired',
            action: 'Reconnect',
          };
        }
        const isDormant = row.last_synced_at ? row.last_synced_at < dormantCutoff : false;
        if (isDormant) {
          return {
            id: row.id,
            handle: row.username ? `@${row.username}` : 'Unnamed account',
            platform,
            severity: 'warn',
            issue: `Dormant ${dormantHours}h+`,
            action: 'Review',
          };
        }
        return null;
      };

      const all: AttentionItem[] = [
        ...(platform !== 'ig'
          ? (((threadsRes.data ?? []) as AcctRow[]).map((r) => classify(r, 'threads')).filter(Boolean) as AttentionItem[])
          : []),
        ...(platform !== 'threads'
          ? (((igRes.data ?? []) as AcctRow[]).map((r) => classify(r, 'instagram')).filter(Boolean) as AttentionItem[])
          : []),
      ];

      all.sort((a, b) => {
        if (a.severity !== b.severity) return a.severity === 'crit' ? -1 : 1;
        return a.handle.localeCompare(b.handle);
      });

      const accountsWithScheduled = new Set<string>();
      for (const post of scheduledRes.data ?? []) {
        const accountKey = post.platform === 'threads' ? post.account_id : post.instagram_account_id;
        if (accountKey) accountsWithScheduled.add(`${post.platform}:${accountKey}`);
      }
      const totalActive =
        (platform !== 'ig' ? (threadsRes.data?.length ?? 0) : 0) +
        (platform !== 'threads' ? (igRes.data?.length ?? 0) : 0);
      const activeWithSchedule =
        (platform !== 'ig'
          ? (threadsRes.data ?? []).filter((r) => accountsWithScheduled.has(`threads:${r.id}`)).length
          : 0) +
        (platform !== 'threads'
          ? (igRes.data ?? []).filter((r) => accountsWithScheduled.has(`instagram:${r.id}`)).length
          : 0);
      const gapsCount = Math.max(0, totalActive - activeWithSchedule);

      return {
        items: all.slice(0, MAX_ROWS),
        totalCount: all.length,
        gapsCount,
      };
    },
  });

  return {
    ...(data ?? EMPTY),
    isLoading: !!userKey && isPending,
    hasError: !!userKey && isError,
  };
}
