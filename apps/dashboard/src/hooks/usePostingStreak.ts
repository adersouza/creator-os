import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';
import { queryClient } from '@/lib/queryClient';
import { computePostingStreak, computeRecentDaysPosted, computeWeekDaysPosted } from '@/utils/postingStreak';
import type { AccountScopeValue } from '@/stores/useAccountScopeStore';

export type StreakPlatform = 'all' | 'threads' | 'ig';

interface State {
  streak: number;
  weekDaysPosted: boolean[];
  recentDaysPosted: boolean[];
  postsThisWeek: number;
  weeklyGoal: number;
  goalHit: boolean;
  isLoading: boolean;
  hasError: boolean;
}

interface PostRow {
  published_at: string | null;
  status: string | null;
  platform: string | null;
  account_id: string | null;
  instagram_account_id: string | null;
}

const EMPTY: State = {
  streak: 0,
  weekDaysPosted: [false, false, false, false, false, false, false],
  recentDaysPosted: Array.from({ length: 14 }, () => false),
  postsThisWeek: 0,
  weeklyGoal: 4,
  goalHit: false,
  isLoading: false,
  hasError: false,
};

const LOOKBACK_DAYS = 60;
const POSTS_LIMIT = 1000;

/**
 * Posting streak — consecutive days with at least one published post,
 * scoped to the chosen platform. Wraps the orphan utilities at
 * `src/utils/postingStreak.ts` (`computePostingStreak`,
 * `computeWeekDaysPosted`).
 */
export function usePostingStreak(
  platform: StreakPlatform = 'all',
  scopedAccount: AccountScopeValue | null = null,
  accountIds?: string[],
  groupId?: string | null,
): State {
  const auth = useAuthUser();
  const userId = auth?.id ?? null;

  const { data, isPending, isError } = useQuery({
    queryKey: ['postingStreak', userId, platform, scopedAccount?.id ?? 'fleet', groupId ?? 'all', accountIds?.join(',') ?? null],
    enabled: !!userId,
    staleTime: 5 * 60 * 1000,
    queryFn: async (): Promise<Omit<State, 'isLoading' | 'hasError'>> => {
      const since = new Date();
      since.setDate(since.getDate() - LOOKBACK_DAYS);

      const rawPosts = await queryClient.fetchQuery<PostRow[]>({
        queryKey: ['postingStreakRaw', userId, scopedAccount?.id ?? 'fleet', groupId ?? 'all', accountIds?.join(',') ?? null],
        staleTime: 5 * 60_000,
        gcTime: 15 * 60_000,
        queryFn: async () => {
          const { data, error } = await supabase
            .from('posts')
            .select('published_at, status, platform, account_id, instagram_account_id')
            .eq('status', 'published')
            .not('published_at', 'is', null)
            .gte('published_at', since.toISOString())
            .order('published_at', { ascending: false })
            .limit(POSTS_LIMIT);

          if (error) throw error;
          return (data ?? []) as PostRow[];
        },
      });

      const posts = rawPosts.filter((post) => {
        if (scopedAccount) {
          if (scopedAccount.platform === 'threads') return post.account_id === scopedAccount.id;
          return post.instagram_account_id === scopedAccount.id;
        }
        if (accountIds && accountIds.length > 0) {
          const postAccountId = post.platform === 'instagram' ? post.instagram_account_id : post.account_id;
          if (!postAccountId || !accountIds.includes(postAccountId)) return false;
        }
        if (platform === 'threads') return post.platform === 'threads';
        if (platform === 'ig') return post.platform === 'instagram';
        return true;
      });
      const postLikes = posts.map((p) => ({ publishedAt: p.published_at, status: p.status ?? 'published' }));

      const streak = computePostingStreak(postLikes);
      const weekDaysPosted = computeWeekDaysPosted(postLikes);
      const recentDaysPosted = computeRecentDaysPosted(postLikes, 14);
      const postsThisWeek = weekDaysPosted.filter(Boolean).length;
      const weeklyGoal = 4;
      const goalHit = postsThisWeek >= weeklyGoal;

      return { streak, weekDaysPosted, recentDaysPosted, postsThisWeek, weeklyGoal, goalHit };
    },
  });

  if (!data) return { ...EMPTY, isLoading: isPending, hasError: !!userId && isError };
  return { ...data, isLoading: isPending, hasError: false };
}
