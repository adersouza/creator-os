import { useQuery } from '@tanstack/react-query';
import { useAuthUser } from '@/hooks/useAuthUser';
import { getApiAuthHeaders } from '@/lib/apiAuth';
import { apiUrl } from '@/lib/apiUrl';
import { queryClient } from '@/lib/queryClient';
import { supabase } from '@/services/supabase';

export interface SaveRateLeader {
  id: string;
  content: string | null;
  publishedAt: string;
  permalink: string | null;
  saved: number;
  reach: number;
  views: number;
  saveRate: number;
  mediaUrl: string | null;
}

interface SaveRateResponse {
  leaders: SaveRateLeader[];
  periodDays: number;
}

interface SaveRateState extends SaveRateResponse {
  isLoading: boolean;
  hasError: boolean;
}

const EMPTY: SaveRateResponse = { leaders: [], periodDays: 14 };

async function fetchLeaders(
  periodDays: number,
  accountId: string | null,
  limit: number,
  accountIds?: string[],
): Promise<SaveRateResponse> {
  const params = new URLSearchParams({
    periodDays: String(periodDays),
    limit: String(limit),
  });
  if (accountId) params.set('accountId', accountId);
  else if (accountIds && accountIds.length > 0) params.set('accountIds', accountIds.join(','));
  const response = await fetch(apiUrl(`/api/analytics?action=save-rate-leaders&${params}`), {
    headers: await getApiAuthHeaders(),
  });
  if (!response.ok) throw new Error('Failed to fetch save-rate leaders');
  const data = (await response.json()) as SaveRateResponse;
  return {
    leaders: data.leaders ?? [],
    periodDays: data.periodDays ?? periodDays,
  };
}

async function fetchPostBackedLeaders(
  userId: string,
  periodDays: number,
  accountId: string | null,
  limit: number,
  accountIds?: string[],
): Promise<SaveRateResponse> {
  const since = new Date();
  since.setDate(since.getDate() - periodDays);
  since.setHours(0, 0, 0, 0);

  const rows = await queryClient.fetchQuery({
    queryKey: ['saveRateLeadersRaw', userId, periodDays, accountId],
    staleTime: 10 * 60_000,
    gcTime: 15 * 60_000,
    queryFn: async () => {
      let query = supabase
        .from('posts')
        .select('id, content, published_at, permalink, ig_saved, ig_reach, ig_views, media_urls')
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
        ig_saved: number | null;
        ig_reach: number | null;
        ig_views: number | null;
        media_urls: string[] | null;
      }>;
    },
  });

  const leaders = rows
    .map((post) => {
      const reach = post.ig_reach || 0;
      const saved = post.ig_saved || 0;
      return {
        id: post.id,
        content: post.content,
        publishedAt: post.published_at,
        permalink: post.permalink,
        saved,
        reach,
        views: post.ig_views || 0,
        saveRate: reach > 0 ? saved / reach : 0,
        mediaUrl: post.media_urls?.[0] ?? null,
      };
    })
    .filter((post) => post.reach > 0 && post.saved > 0)
    .sort((a, b) => b.saveRate - a.saveRate)
    .slice(0, limit);

  return { leaders, periodDays };
}

export function useSaveRateLeaders(
  periodDays: number = 14,
  accountId: string | null = null,
  limit: number = 5,
  accountIds?: string[],
): SaveRateState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending, isError } = useQuery<SaveRateResponse>({
    queryKey: ['saveRateLeaders', userKey, periodDays, accountId, accountIds?.join(',') ?? null, limit],
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
    ...(data ?? EMPTY),
    isLoading: !!userKey && isPending,
    hasError: !!userKey && isError,
  };
}
