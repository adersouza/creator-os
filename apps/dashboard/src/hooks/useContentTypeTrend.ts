import { useQuery } from '@tanstack/react-query';
import { useAuthUser } from '@/hooks/useAuthUser';
import { getApiAuthHeaders } from '@/lib/apiAuth';
import { apiUrl } from '@/lib/apiUrl';

/** Per-metric numeric snapshot for a given media type. */
export type MetricBucket = Record<string, number>;
export type ContentBuckets = Record<string, MetricBucket>;

export interface MetricDelta {
  current: number;
  previous: number;
  delta: number;
  pctChange: number;
}

export type ContentDeltas = Record<string, Record<string, MetricDelta>>;

export interface ContentTypeTrendResponse {
  current: ContentBuckets;
  previous: ContentBuckets;
  deltas: ContentDeltas;
}

interface State {
  data: ContentTypeTrendResponse | null;
  isLoading: boolean;
  hasError: boolean;
}

async function fetchContentTypeTrend(
  accountIds: string[] | null,
  accountId: string | null,
  groupId: string | null,
): Promise<ContentTypeTrendResponse> {
  const params = new URLSearchParams();
  if (accountId) params.set('accountId', accountId);
  else if (groupId) params.set('groupId', groupId);
  else if (accountIds && accountIds.length > 0) params.set('accountIds', accountIds.join(','));
  const response = await fetch(
    apiUrl(`/api/analytics?action=content-type-trend&${params}`),
    {
      headers: await getApiAuthHeaders(),
    },
  );
  if (!response.ok) throw new Error('Failed to fetch content-type trend');
  const data = (await response.json()) as ContentTypeTrendResponse;
  return {
    current: data.current ?? {},
    previous: data.previous ?? {},
    deltas: data.deltas ?? {},
  };
}

/**
 * IG content-type WoW comparison. Endpoint at
 * api/analytics?action=content-type-trend sums `ig_content_type_breakdown`
 * across the last 7 days vs the prior 7. Returns per-format per-metric
 * deltas + pct changes for direct rendering.
 */
export function useContentTypeTrend(
  accountIds?: string[],
  accountId?: string | null,
  groupId?: string | null,
  enabled: boolean = true,
): State {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;
  const ids = accountIds ?? null;
  const queryEnabled = enabled && !!userKey;

  const { data, isPending, isError } = useQuery<ContentTypeTrendResponse>({
    queryKey: ['contentTypeTrend', userKey, accountId ?? null, groupId ?? 'all', ids?.join(',') ?? null],
    enabled: queryEnabled,
    staleTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
    queryFn: () => fetchContentTypeTrend(ids, accountId ?? null, groupId ?? null),
  });

  return {
    data: data ?? null,
    isLoading: queryEnabled && isPending,
    hasError: queryEnabled && isError,
  };
}
