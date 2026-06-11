import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';

export interface ThreadsQuoteRatioState {
  quotes: number;
  reposts: number;
  ratio: number;
  trend: number[];
  hasRealData: boolean;
  loading: boolean;
}

const EMPTY: Omit<ThreadsQuoteRatioState, 'loading'> = {
  quotes: 0,
  reposts: 0,
  ratio: 0,
  trend: [],
  hasRealData: false,
};

const MIN_POSTS = 5;

function daysToCutoff(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  d.setHours(0, 0, 0, 0);
  return d.toISOString();
}

export function useThreadsQuoteRatio(
  timeframeDays: number,
  accountId: string | null = null,
): ThreadsQuoteRatioState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending } = useQuery({
    queryKey: ['threadsQuoteRatio', userKey, timeframeDays, accountId],
    enabled: !!userKey,
    queryFn: async () => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return EMPTY;

      const since = daysToCutoff(timeframeDays);
      let query = supabase
        .from('posts')
        .select('quotes_count, reposts_count, published_at')
        .eq('user_id', user.id)
        .eq('platform', 'threads')
        .eq('status', 'published')
        .gte('published_at', since)
        .not('published_at', 'is', null);
      if (accountId) query = query.eq('account_id', accountId);

      const { data: posts, error } = await query;

      if (error) throw error;
      if (!posts || posts.length < MIN_POSTS) return EMPTY;

      type PostRow = {
        quotes_count: number | null;
        reposts_count: number | null;
        published_at: string | null;
      };

      let totalQuotes = 0;
      let totalReposts = 0;
      const dayBuckets = new Map<string, { quotes: number; reposts: number }>();

      for (const p of posts as PostRow[]) {
        const q = p.quotes_count ?? 0;
        const r = p.reposts_count ?? 0;
        totalQuotes += q;
        totalReposts += r;

        if (p.published_at) {
          const day = p.published_at.slice(0, 10);
          const bucket = dayBuckets.get(day) ?? { quotes: 0, reposts: 0 };
          bucket.quotes += q;
          bucket.reposts += r;
          dayBuckets.set(day, bucket);
        }
      }

      if (totalQuotes + totalReposts === 0) return EMPTY;

      const ratio = (totalQuotes / (totalQuotes + totalReposts)) * 100;

      const sortedDays = Array.from(dayBuckets.entries()).sort(([a], [b]) => a.localeCompare(b));
      const trend = sortedDays.map(([, { quotes, reposts }]) => {
        const total = quotes + reposts;
        return total > 0 ? Math.round((quotes / total) * 100) : 0;
      });

      return { quotes: totalQuotes, reposts: totalReposts, ratio, trend, hasRealData: true };
    },
  });

  return {
    ...(data ?? EMPTY),
    loading: !!userKey && isPending,
  };
}
