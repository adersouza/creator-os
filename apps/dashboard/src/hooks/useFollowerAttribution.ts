import { useQuery } from '@tanstack/react-query';
import { useAuthUser } from '@/hooks/useAuthUser';
import { getApiAuthHeaders } from '@/lib/apiAuth';
import { apiUrl } from '@/lib/apiUrl';
import type { AccountScopeValue } from '@/stores/useAccountScopeStore';

export interface FollowerAttributionPost {
  id: string;
  content: string | null;
  likes: number;
  replies: number;
  views: number;
  permalink: string | null;
}

export interface FollowerAttributionDay {
  date: string;
  followerGrowth: number;
  posts: FollowerAttributionPost[];
}

interface FollowerAttributionResponse {
  days: FollowerAttributionDay[];
  periodDays: number;
}

interface FollowerAttributionState {
  days: FollowerAttributionDay[];
  periodDays: number;
  isLoading: boolean;
  hasError: boolean;
}

async function fetchFollowerAttribution(
  periodDays: number,
  platform: 'threads' | 'instagram' | null,
  accountId: string | null,
  accountIds?: string[],
): Promise<FollowerAttributionResponse> {
  const params = new URLSearchParams({ periodDays: String(periodDays) });
  if (platform) params.set('platform', platform);
  if (accountId) params.set('accountId', accountId);
  if (!accountId && accountIds && accountIds.length > 0) params.set('accountIds', accountIds.join(','));
  const response = await fetch(apiUrl(`/api/analytics?action=follower-attribution&${params}`), {
    headers: await getApiAuthHeaders(),
  });
  if (!response.ok) {
    let message = 'Failed to fetch follower attribution';
    if (response.headers.get('content-type')?.includes('application/json')) {
      const body = (await response.json().catch(() => null)) as { error?: string } | null;
      message = body?.error || message;
    }
    throw Object.assign(new Error(message), { status: response.status });
  }
  const data = (await response.json()) as FollowerAttributionResponse & { success?: boolean | undefined };
  return { days: data.days ?? [], periodDays: data.periodDays ?? periodDays };
}

/**
 * Attributes daily net-follower change to the posts published that day.
 * No prediction — just joins account_analytics.follower_growth to posts.
 * Daily cache: analytics rollups run every 15min so a minute of staleness
 * is fine. Window focus refetch off — the data is batched per day.
 */
export function useFollowerAttribution(
  periodDays: number = 30,
  platform: 'threads' | 'instagram' | null = null,
  scopedAccount: AccountScopeValue | null = null,
  accountIds?: string[],
  groupId?: string | null,
): FollowerAttributionState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;
  const accountId = scopedAccount?.id ?? null;
  const resolvedPlatform = scopedAccount?.platform ?? platform;

  const { data, isPending, isError } = useQuery<FollowerAttributionResponse>({
    queryKey: ['followerAttribution', userKey, periodDays, resolvedPlatform, accountId ?? 'fleet', groupId ?? 'all', accountIds?.join(',') ?? null],
    enabled: !!userKey,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    throwOnError: false,
    queryFn: () => fetchFollowerAttribution(periodDays, resolvedPlatform, accountId, accountIds),
  });

  return {
    days: data?.days ?? [],
    periodDays: data?.periodDays ?? periodDays,
    isLoading: !!userKey && isPending,
    hasError: !!userKey && isError,
  };
}
