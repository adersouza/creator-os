import { useQuery } from '@tanstack/react-query';
import { useAuthUser } from '@/hooks/useAuthUser';
import { getApiAuthHeaders } from '@/lib/apiAuth';
import { apiUrl } from '@/lib/apiUrl';

export interface WatchTimeLeader {
  id: string;
  content: string | null;
  publishedAt: string;
  permalink: string | null;
  avgWatchMs: number;
  views: number;
  reach: number;
}

interface WatchTimeResponse {
  leaders: WatchTimeLeader[];
  periodDays: number;
}

interface WatchTimeState extends WatchTimeResponse {
  isLoading: boolean;
  hasError: boolean;
}

const EMPTY: WatchTimeResponse = { leaders: [], periodDays: 14 };

async function fetchLeaders(
  periodDays: number,
  accountId: string | null,
): Promise<WatchTimeResponse> {
  const params = new URLSearchParams({ periodDays: String(periodDays) });
  if (accountId) params.set('accountId', accountId);
  const response = await fetch(apiUrl(`/api/analytics?action=watch-time-leaders&${params}`), {
    headers: await getApiAuthHeaders(),
  });
  if (!response.ok) throw new Error('Failed to fetch watch-time leaders');
  const data = (await response.json()) as WatchTimeResponse;
  return {
    leaders: data.leaders ?? [],
    periodDays: data.periodDays ?? periodDays,
  };
}

/**
 * Top IG Reels by average watch time. IG-only.
 */
export function useWatchTimeLeaders(
  periodDays: number = 14,
  accountId: string | null = null,
): WatchTimeState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending, isError } = useQuery<WatchTimeResponse>({
    queryKey: ['watchTimeLeaders', userKey, periodDays, accountId],
    enabled: !!userKey,
    staleTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
    queryFn: () => fetchLeaders(periodDays, accountId),
  });

  return {
    ...(data ?? EMPTY),
    isLoading: !!userKey && isPending,
    hasError: !!userKey && isError,
  };
}
