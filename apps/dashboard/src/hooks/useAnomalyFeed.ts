import { useQuery } from '@tanstack/react-query';
import { useAuthUser } from '@/hooks/useAuthUser';
import { getApiAuthHeaders } from '@/lib/apiAuth';
import { apiUrl } from '@/lib/apiUrl';
import { toHours, toLabel, type TimeRangeInput } from '@/lib/timeRange';
import type { AccountScopeValue } from '@/stores/useAccountScopeStore';

export type AnomalyFilter = 'all' | 'reach-suppression';

export interface AnomalyAlert {
  id: string;
  accountId: string | null;
  instagramAccountId: string | null;
  platform: string;
  alertType: string;
  severity: string;
  title: string;
  description: string | null;
  aiAnalysis: string | null;
  data: Record<string, unknown> | null;
  createdAt: string | null;
}

interface AnomalyFeedResponse {
  alerts: AnomalyAlert[];
  periodHours: number;
  filter: string | null;
  total: number;
}

interface AnomalyFeedState extends AnomalyFeedResponse {
  isLoading: boolean;
  hasError: boolean;
  refetch: () => void;
}

const EMPTY: AnomalyFeedResponse = { alerts: [], periodHours: 24, filter: null, total: 0 };

async function fetchFeed(
  periodHours: number,
  filter: AnomalyFilter,
  scopedAccount: AccountScopeValue | null,
  accountIds?: string[],
): Promise<AnomalyFeedResponse> {
  const params = new URLSearchParams({ periodHours: String(periodHours) });
  if (filter !== 'all') params.set('filter', filter);
  if (scopedAccount) {
    params.set('accountId', scopedAccount.id);
    params.set('platform', scopedAccount.platform);
  } else if (accountIds && accountIds.length > 0) {
    params.set('accountIds', accountIds.join(','));
  }
  const response = await fetch(apiUrl(`/api/analytics?action=anomaly-feed&${params}`), {
    headers: await getApiAuthHeaders(),
  });
  if (!response.ok) throw new Error('Failed to fetch anomaly feed');
  const data = (await response.json()) as AnomalyFeedResponse;
  return {
    alerts: data.alerts ?? [],
    periodHours: data.periodHours ?? periodHours,
    filter: data.filter ?? null,
    total: data.total ?? 0,
  };
}

/**
 * Unresolved anomaly alerts for the logged-in user, sorted by severity then
 * freshness. Backend reads anomaly_alerts populated nightly by
 * anomalyDetector + audienceShiftDetector crons.
 */
export function useAnomalyFeed(
  periodHours: TimeRangeInput = { hours: 24 },
  filter: AnomalyFilter = 'all',
  scopedAccount: AccountScopeValue | null = null,
  accountIds?: string[],
  groupId?: string | null,
): AnomalyFeedState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;
  const rangeForHours = typeof periodHours === 'number' ? { hours: periodHours } : periodHours;
  const hours = toHours(rangeForHours);
  const periodLabel = toLabel(rangeForHours);

  const { data, isPending, isError, refetch } = useQuery<AnomalyFeedResponse>({
    queryKey: ['anomalyFeed', userKey, periodLabel, filter, scopedAccount?.id ?? 'fleet', groupId ?? 'all', accountIds?.join(',') ?? null],
    enabled: !!userKey,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    queryFn: () => fetchFeed(hours, filter, scopedAccount, accountIds),
  });

  return {
    ...(data ?? EMPTY),
    isLoading: !!userKey && isPending,
    hasError: !!userKey && isError,
    refetch: () => {
      void refetch();
    },
  };
}
