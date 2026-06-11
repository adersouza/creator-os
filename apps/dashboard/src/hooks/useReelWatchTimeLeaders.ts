import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';
import { fetchConnectedAccounts } from '@/hooks/useConnectedAccounts';
import { queryClient } from '@/lib/queryClient';
import { queryKeys } from '@/lib/queryKeys';
import type { AccountScopeValue } from '@/stores/useAccountScopeStore';

export interface ReelWatchLeader {
  id: string;
  instagramAccountId: string | null;
  username: string | null;
  content: string | null;
  publishedAt: string | null;
  permalink: string | null;
  /** Average watch time per view, in seconds (rounded 0.1). */
  avgWatchSec: number;
  /** Completion proxy: total watch time / views. Same units as avgWatchSec when
   *  per-view (no replays) — included for future leaderboard refinement. */
  totalWatchSec: number;
  views: number;
  /** ig_skip_rate column (0..1). Proxy for hook-strength histogram in mockup
   *  new-widgets-2026 #3. Meta API does NOT expose per-second retention. */
  igSkipRate: number | null;
}

interface State {
  leaders: ReelWatchLeader[];
  periodDays: number;
  isLoading: boolean;
  hasError: boolean;
}

interface PostRow {
  id: string;
  content: string | null;
  published_at: string | null;
  permalink: string | null;
  instagram_account_id: string | null;
  ig_reels_avg_watch_time: number | null;
  ig_reels_video_view_total_time: number | null;
  ig_skip_rate: number | null;
  views_count: number | null;
}

/**
 * Top IG Reels ranked by average watch-time per view (Mosseri's #1 retention
 * signal). Queries `posts` directly — no /api endpoint — so it works in
 * local dev and doesn't need a new serverless function.
 *
 * Ranks descending by `ig_reels_avg_watch_time` (ms → seconds). Per-Reel
 * duration isn't reliably exposed by Meta, so we rank on absolute watch
 * time rather than watch/view-duration ratio. The research (§4) describes
 * this as acceptable for the home glance view; normalization belongs on
 * Analytics.
 */
export function useReelWatchTimeLeaders(
  periodDays: number = 7,
  scopedAccount: AccountScopeValue | null = null,
  accountIds?: string[],
  groupId?: string | null,
): State {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const accountId =
    scopedAccount?.platform === 'instagram'
      ? scopedAccount.id
      : null;

  const { data, isPending, isError } = useQuery<Omit<State, 'isLoading' | 'hasError'>>({
    queryKey: ['reelWatchTimeLeaders', userKey, periodDays, accountId ?? 'fleet', groupId ?? 'all', accountIds?.join(',') ?? null],
    enabled: !!userKey,
    staleTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
    queryFn: async () => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return { leaders: [], periodDays };

      const since = new Date();
      since.setDate(since.getDate() - periodDays);
      since.setHours(0, 0, 0, 0);

      const [postsRes, accountsRes] = await Promise.all([
        (() => {
          let q = supabase
            .from('posts')
            .select('id, content, published_at, permalink, instagram_account_id, ig_reels_avg_watch_time, ig_reels_video_view_total_time, ig_skip_rate, views_count')
            .eq('user_id', user.id)
            .eq('platform', 'instagram')
            .eq('status', 'published')
            .not('ig_reels_avg_watch_time', 'is', null)
            .gt('ig_reels_avg_watch_time', 0)
            .gte('published_at', since.toISOString())
            .order('ig_reels_avg_watch_time', { ascending: false })
            .limit(20);
          if (accountId) q = q.eq('instagram_account_id', accountId);
          else if (accountIds && accountIds.length > 0) q = q.in('instagram_account_id', accountIds);
          return q;
        })(),
        queryClient.fetchQuery({
          queryKey: queryKeys.accounts.connected(user.id),
          staleTime: 5 * 60_000,
          gcTime: 15 * 60_000,
          queryFn: () => fetchConnectedAccounts(user.id),
        }),
      ]);

      if (postsRes.error) throw postsRes.error;

      const nameFor = new Map<string, string | null>();
      for (const account of accountsRes) {
        if (account.platform === 'instagram') {
          nameFor.set(account.id, account.handle.replace(/^@/, ''));
        }
      }

      const leaders: ReelWatchLeader[] = ((postsRes.data ?? []) as PostRow[]).map((p) => {
        const avgMs = p.ig_reels_avg_watch_time ?? 0;
        const totalMs = p.ig_reels_video_view_total_time ?? 0;
        return {
          id: p.id,
          instagramAccountId: p.instagram_account_id,
          username: p.instagram_account_id ? nameFor.get(p.instagram_account_id) ?? null : null,
          content: p.content,
          publishedAt: p.published_at,
          permalink: p.permalink,
          avgWatchSec: Math.round((avgMs / 1000) * 10) / 10,
          totalWatchSec: Math.round((totalMs / 1000) * 10) / 10,
          views: p.views_count ?? 0,
          igSkipRate: p.ig_skip_rate ?? null,
        };
      });

      return { leaders, periodDays };
    },
  });

  return {
    leaders: data?.leaders ?? [],
    periodDays: data?.periodDays ?? periodDays,
    isLoading: !!userKey && isPending,
    hasError: !!userKey && isError,
  };
}
