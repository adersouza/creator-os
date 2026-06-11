import { useQuery } from '@tanstack/react-query';
import { useAuthUser } from '@/hooks/useAuthUser';
import { getApiAuthHeaders } from '@/lib/apiAuth';
import { apiUrl } from '@/lib/apiUrl';

export interface HashtagPerformanceRow {
  hashtag: string;
  postCount: number;
  platforms: string[];
  totalViews: number;
  totalReach: number;
  totalLikes: number;
  totalReplies: number;
  totalSaves: number;
  totalShares: number;
  avgEngagementRate: number;
}

export interface HashtagPerformanceResponse {
  hashtags: HashtagPerformanceRow[];
  totalPosts: number;
}

interface State {
  data: HashtagPerformanceResponse | null;
  isLoading: boolean;
  hasError: boolean;
}

async function fetchHashtagPerformance(
  accountIds: string[] | null,
  accountId: string | null,
  groupId: string | null,
  periodDays: number,
  platform: 'all' | 'threads' | 'instagram',
  limit: number,
): Promise<HashtagPerformanceResponse> {
  const params = new URLSearchParams({
    periodDays: String(periodDays),
    platform,
    limit: String(limit),
  });
  if (accountId) params.set('accountId', accountId);
  else if (groupId) params.set('groupId', groupId);
  else if (accountIds && accountIds.length > 0) params.set('accountIds', accountIds.join(','));
  const response = await fetch(
    apiUrl(`/api/analytics?action=hashtag-performance&${params}`),
    {
      headers: await getApiAuthHeaders(),
    },
  );
  if (!response.ok) throw new Error('Failed to fetch hashtag performance');
  const data = (await response.json()) as HashtagPerformanceResponse;
  return {
    hashtags: data.hashtags ?? [],
    totalPosts: data.totalPosts ?? 0,
  };
}

export interface UseHashtagPerformanceArgs {
  accountIds?: string[] | undefined;
  accountId?: string | null | undefined;
  groupId?: string | null | undefined;
  periodDays?: number | undefined;
  platform?: 'all' | 'threads' | 'instagram' | undefined;
  limit?: number | undefined;
  enabled?: boolean | undefined;
}

/**
 * Per-hashtag aggregated performance over the period. Endpoint at
 * api/analytics?action=hashtag-performance reads `posts` rows + extracts
 * `#tags` from content. Useful for ranking which tags drive reach + ER.
 */
// Signature pattern: options object because every parameter is optional and scope-specific.
export function useHashtagPerformance(args: UseHashtagPerformanceArgs = {}): State {
  const {
    accountIds,
    accountId = null,
    groupId = null,
    periodDays = 30,
    platform = 'instagram',
    limit = 25,
    enabled: enabledArg = true,
  } = args;
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;
  const ids = accountIds ?? null;
  const enabled = enabledArg && !!userKey;

  const { data, isPending, isError } = useQuery<HashtagPerformanceResponse>({
    queryKey: ['hashtagPerformance', userKey, accountId, groupId ?? 'all', ids?.join(','), periodDays, platform, limit],
    enabled,
    staleTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
    queryFn: () => fetchHashtagPerformance(ids, accountId, groupId, periodDays, platform, limit),
  });

  return {
    data: data ?? null,
    isLoading: enabled && isPending,
    hasError: enabled && isError,
  };
}
