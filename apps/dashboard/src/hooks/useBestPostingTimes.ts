import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';
import { queryKeys } from '@/lib/queryKeys';

export interface BestPostingTimes {
  /** Top 2 hours (0–23) ranked by engagement rate. Empty until hydrated or insufficient data. */
  topHours: number[];
  /** False until ≥5 published posts exist in the scope; heuristic is only meaningful beyond that. */
  hasEnoughData: boolean;
  isLoading: boolean;
}

const MIN_POSTS = 5;
const LOOKBACK_DAYS = 60;

interface PostRow {
  platform: string | null;
  published_at: string | null;
  likes_count: number | null;
  replies_count: number | null;
  reposts_count: number | null;
  views_count: number | null;
  ig_reach: number | null;
}

interface Result {
  topHours: number[];
  hasEnoughData: boolean;
}

const EMPTY: Result = { topHours: [], hasEnoughData: false };

/**
 * Best times to post for a given account scope, derived from the user's own published-post
 * engagement × hour-of-day. Engagement rate = weighted(likes, replies, reposts) / reach.
 *
 * @param accountId — single target account id (Threads `account_id` or Instagram
 *   `instagram_account_id`), or null for fleet-wide (all accounts). When composer
 *   has multiple targets, null is the right scope since a mixed-account post can't
 *   be per-account optimized anyway.
 */
export function useBestPostingTimes(accountId: string | null): BestPostingTimes {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending } = useQuery({
    queryKey: queryKeys.analytics.bestPostingTimes(userKey, accountId),
    enabled: !!userKey,
    staleTime: 10 * 60_000,
    queryFn: async (): Promise<Result> => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return EMPTY;

      const since = new Date();
      since.setDate(since.getDate() - LOOKBACK_DAYS);

      let query = supabase
        .from('posts')
        .select('platform, published_at, likes_count, replies_count, reposts_count, views_count, ig_reach')
        .eq('user_id', user.id)
        .eq('status', 'published')
        .gte('published_at', since.toISOString())
        .limit(500);

      if (accountId) {
        query = query.or(`account_id.eq.${accountId},instagram_account_id.eq.${accountId}`);
      }

      const { data, error } = await query;

      if (error) throw error;
      if (!data || data.length < MIN_POSTS) return EMPTY;

      return {
        topHours: computeTopHours(data),
        hasEnoughData: true,
      };
    },
  });

  return {
    ...(data ?? EMPTY),
    isLoading: !!userKey && isPending,
  };
}

function computeTopHours(rows: PostRow[]): number[] {
  const buckets = new Map<number, { engagement: number; views: number; count: number }>();

  for (const row of rows) {
    if (!row.published_at) continue;
    const hour = new Date(row.published_at).getHours();
    const engagement =
      (row.likes_count ?? 0) +
      (row.replies_count ?? 0) * 2 +
      (row.reposts_count ?? 0) * 1.5;
    const reach = row.platform === 'instagram'
      ? (row.ig_reach ?? row.views_count ?? 0)
      : (row.views_count ?? 0);
    const views = Math.max(1, reach);

    const b = buckets.get(hour);
    if (b) {
      b.engagement += engagement;
      b.views += views;
      b.count += 1;
    } else {
      buckets.set(hour, { engagement, views, count: 1 });
    }
  }

  return Array.from(buckets.entries())
    .filter(([, b]) => b.count >= 2)
    .map(([hour, b]) => ({ hour, rate: b.engagement / b.views }))
    .sort((a, b) => b.rate - a.rate)
    .slice(0, 2)
    .map((e) => e.hour);
}

/** Format a 24h hour as "7pm" / "9am" / "12pm". */
export function formatHour(hour: number): string {
  if (hour === 0) return '12am';
  if (hour === 12) return '12pm';
  if (hour < 12) return `${hour}am`;
  return `${hour - 12}pm`;
}

/** Join up to 2 hours with a middle-dot separator: "7pm · 9am". Empty string when none. */
export function formatBestHours(hours: number[]): string {
  return hours.slice(0, 2).map(formatHour).join(' · ');
}
