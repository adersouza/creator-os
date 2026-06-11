import { useQuery } from '@tanstack/react-query';
import { useAuthUser } from '@/hooks/useAuthUser';
import { getApiAuthHeaders } from '@/lib/apiAuth';
import { apiUrl } from '@/lib/apiUrl';
import { queryClient } from '@/lib/queryClient';
import { supabase } from '@/services/supabase';

export interface SendsPerReachLeader {
  id: string;
  content: string | null;
  publishedAt: string;
  permalink: string | null;
  reach: number;
  shares: number;
  views: number;
  sendsPerReach: number;
  instagramAccountId: string | null;
}

interface SendsPerReachResponse {
  leaders: SendsPerReachLeader[];
  periodDays: number;
}

interface SendsPerReachState {
  leaders: SendsPerReachLeader[];
  periodDays: number;
  isLoading: boolean;
  hasError: boolean;
}

async function fetchLeaders(
  periodDays: number,
  accountId: string | null,
  limit: number,
  accountIds?: string[],
): Promise<SendsPerReachResponse> {
  const params = new URLSearchParams({
    periodDays: String(periodDays),
    limit: String(limit),
  });
  if (accountId) params.set('accountId', accountId);
  else if (accountIds && accountIds.length > 0) params.set('accountIds', accountIds.join(','));
  const response = await fetch(apiUrl(`/api/analytics?action=sends-per-reach-leaders&${params}`), {
    headers: await getApiAuthHeaders(),
  });
  if (!response.ok) throw new Error('Failed to fetch sends-per-reach leaders');
  const data = (await response.json()) as SendsPerReachResponse;
  return { leaders: data.leaders ?? [], periodDays: data.periodDays ?? periodDays };
}

async function fetchPostBackedLeaders(
  userId: string,
  periodDays: number,
  accountId: string | null,
  limit: number,
  accountIds?: string[],
): Promise<SendsPerReachResponse> {
  const since = new Date();
  since.setDate(since.getDate() - periodDays);
  since.setHours(0, 0, 0, 0);

  const rows = await queryClient.fetchQuery({
    queryKey: ['sendsPerReachLeadersRaw', userId, periodDays, accountId],
    staleTime: 10 * 60_000,
    gcTime: 15 * 60_000,
    queryFn: async () => {
      let query = supabase
        .from('posts')
        .select('id, content, published_at, permalink, instagram_account_id, ig_reach, ig_shares, shares_count, ig_views')
        .eq('user_id', userId)
        .eq('platform', 'instagram')
        .eq('status', 'published')
        .gt('ig_reach', 0)
        .gte('published_at', since.toISOString());
      if (accountId) query = query.eq('instagram_account_id', accountId);
      else if (accountIds && accountIds.length > 0) query = query.in('instagram_account_id', accountIds);

      const { data, error } = await query;
      if (error) throw error;
      return (data ?? []) as unknown as Array<{
        id: string;
        content: string | null;
        published_at: string;
        permalink: string | null;
        instagram_account_id: string | null;
        ig_reach: number | null;
        ig_shares: number | null;
        shares_count: number | null;
        ig_views: number | null;
      }>;
    },
  });

  const leaders = rows
    .map((post) => {
      const reach = post.ig_reach || 0;
      const shares = post.ig_shares || post.shares_count || 0;
      return {
        id: post.id,
        content: post.content,
        publishedAt: post.published_at,
        permalink: post.permalink,
        reach,
        shares,
        views: post.ig_views || 0,
        sendsPerReach: reach > 0 ? shares / reach : 0,
        instagramAccountId: post.instagram_account_id,
      };
    })
    .filter((post) => post.reach > 0 && post.shares > 0)
    .sort((a, b) => b.sendsPerReach - a.sendsPerReach)
    .slice(0, limit);

  return { leaders, periodDays };
}

/**
 * Top IG posts by shares/reach ratio — a strong distribution signal across
 * IG formats. Cache 10min; IG insights update in the same ~15min
 * analytics-pipeline window.
 */
export function useSendsPerReachLeaders(
  periodDays: number = 14,
  accountId: string | null = null,
  limit: number = 5,
  accountIds?: string[],
): SendsPerReachState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending, isError } = useQuery<SendsPerReachResponse>({
    queryKey: ['sendsPerReachLeaders', userKey, periodDays, accountId, accountIds?.join(',') ?? null, limit],
    enabled: !!userKey,
    staleTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
    queryFn: async () => {
      const postBacked = await fetchPostBackedLeaders(userKey as string, periodDays, accountId, limit, accountIds);
      if (postBacked.leaders.length > 0) return postBacked;
      return fetchLeaders(periodDays, accountId, limit, accountIds).catch(() => postBacked);
    },
  });

  return {
    leaders: data?.leaders ?? [],
    periodDays: data?.periodDays ?? periodDays,
    isLoading: !!userKey && isPending,
    hasError: !!userKey && isError,
  };
}
