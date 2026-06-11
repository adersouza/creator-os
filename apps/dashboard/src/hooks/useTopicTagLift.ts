import { useQuery } from '@tanstack/react-query';
import { useAuthUser } from '@/hooks/useAuthUser';
import { getApiAuthHeaders } from '@/lib/apiAuth';
import { apiUrl } from '@/lib/apiUrl';
import type { AccountScopeValue } from '@/stores/useAccountScopeStore';

export interface TopicTagLift {
  topic: string;
  windowAvgReach: number;
  baselineAvgReach: number;
  lift: number | null;
  windowPosts: number;
}

interface TopicTagResponse {
  topics: TopicTagLift[];
  periodDays: number;
  baselineDays: number;
}

interface TopicTagState extends TopicTagResponse {
  isLoading: boolean;
  hasError: boolean;
}

const EMPTY: TopicTagResponse = { topics: [], periodDays: 30, baselineDays: 90 };

async function fetchLift(
  periodDays: number,
  baselineDays: number,
  accountId: string | null,
  platform: 'all' | 'instagram' | 'threads',
  accountIds?: string[],
): Promise<TopicTagResponse> {
  const params = new URLSearchParams({
    periodDays: String(periodDays),
    baselineDays: String(baselineDays),
    platform,
  });
  if (accountId) params.set('accountId', accountId);
  if (!accountId && accountIds && accountIds.length > 0) params.set('accountIds', accountIds.join(','));
  const response = await fetch(apiUrl(`/api/analytics?action=topic-tag-lift&${params}`), {
    headers: await getApiAuthHeaders(),
  });
  if (!response.ok) throw new Error('Failed to fetch topic-tag lift');
  const data = (await response.json()) as TopicTagResponse;
  return {
    topics: data.topics ?? [],
    periodDays: data.periodDays ?? periodDays,
    baselineDays: data.baselineDays ?? baselineDays,
  };
}

/**
 * Threads topic-tag lift: avg reach for each topic in the recent window
 * relative to its own longer baseline. Sorted by lift DESC.
 */
export function useTopicTagLift(
  periodDays: number = 30,
  baselineDays: number = 90,
  scopedAccount: AccountScopeValue | null = null,
  platform: 'all' | 'instagram' | 'threads' = 'all',
  accountIds?: string[],
  groupId?: string | null,
): TopicTagState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;
  const accountId =
    scopedAccount && (platform === 'all' || scopedAccount.platform === platform)
      ? scopedAccount.id
      : null;
  const scopedPlatform = scopedAccount?.platform ?? null;

  const { data, isPending, isError } = useQuery<TopicTagResponse>({
    queryKey: ['topicTagLift', userKey, periodDays, baselineDays, accountId ?? 'fleet', scopedPlatform, platform, groupId ?? 'all', accountIds?.join(',') ?? null],
    enabled: !!userKey,
    staleTime: 15 * 60 * 1000,
    refetchOnWindowFocus: false,
    queryFn: () => fetchLift(periodDays, baselineDays, accountId, platform, accountIds),
  });

  return {
    ...(data ?? EMPTY),
    isLoading: !!userKey && isPending,
    hasError: !!userKey && isError,
  };
}
