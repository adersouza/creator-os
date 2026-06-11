import { useQuery } from '@tanstack/react-query';
import { useAuthUser } from '@/hooks/useAuthUser';
import { getApiAuthHeaders } from '@/lib/apiAuth';
import { apiUrl } from '@/lib/apiUrl';

export interface SkipRateAlert {
  id: string;
  content: string | null;
  publishedAt: string;
  permalink: string | null;
  skipRate: number;
  views: number;
  reach: number;
}

interface SkipRateResponse {
  alerts: SkipRateAlert[];
  threshold: number;
  periodDays: number;
}

interface SkipRateState {
  alerts: SkipRateAlert[];
  threshold: number;
  periodDays: number;
  isLoading: boolean;
  hasError: boolean;
}

async function fetchAlerts(
  periodDays: number,
  threshold: number,
  accountId: string | null,
  accountIds?: string[],
  groupId?: string | null,
): Promise<SkipRateResponse> {
  const params = new URLSearchParams({
    periodDays: String(periodDays),
    threshold: String(threshold),
  });
  if (accountId) params.set('accountId', accountId);
  else if (groupId) params.set('groupId', groupId);
  else if (accountIds && accountIds.length > 0) params.set('accountIds', accountIds.join(','));
  const response = await fetch(apiUrl(`/api/analytics?action=skip-rate-alerts&${params}`), {
    headers: await getApiAuthHeaders(),
  });
  if (!response.ok) throw new Error('Failed to fetch skip-rate alerts');
  const data = (await response.json()) as SkipRateResponse;
  return {
    alerts: data.alerts ?? [],
    threshold: data.threshold ?? threshold,
    periodDays: data.periodDays ?? periodDays,
  };
}

/**
 * Reels above the skip-rate threshold in the given window. Defaults: 14-day
 * window, 50% threshold. Highest skip rate first — the triage order.
 */
export function useSkipRateAlerts(
  periodDays: number = 14,
  threshold: number = 0.5,
  accountId: string | null = null,
  accountIds?: string[],
  groupId?: string | null,
): SkipRateState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending, isError } = useQuery<SkipRateResponse>({
    queryKey: ['skipRateAlerts', userKey, periodDays, threshold, accountId, groupId ?? null, accountIds?.join(',') ?? null],
    enabled: !!userKey,
    staleTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
    queryFn: () => fetchAlerts(periodDays, threshold, accountId, accountIds, groupId),
  });

  return {
    alerts: data?.alerts ?? [],
    threshold: data?.threshold ?? threshold,
    periodDays: data?.periodDays ?? periodDays,
    isLoading: !!userKey && isPending,
    hasError: !!userKey && isError,
  };
}
