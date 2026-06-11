import { useQuery } from '@tanstack/react-query';
import { useAuthUser } from '@/hooks/useAuthUser';
import { getApiAuthHeaders } from '@/lib/apiAuth';
import { apiUrl } from '@/lib/apiUrl';

export type Severity = 'critical' | 'warning' | 'healthy' | 'insufficient';

export interface AccountSeverity {
  accountId: string;
  metric: 'threads_views' | 'ig_reach';
  current7d: number;
  baselineMean: number;
  baselineStd: number;
  /** (current7d − baselineMean) / baselineStd. null when baselineStd == 0 or <14 days of history. */
  z: number | null;
  lastDayDelta: number;
  severity: Severity;
}

export interface SeverityScoreData {
  accounts: Record<string, AccountSeverity>;
  missing: string[];
}

interface SeverityScoreState {
  data: SeverityScoreData | null;
  isLoading: boolean;
  hasError: boolean;
  get(accountId: string): AccountSeverity | null;
}

async function fetchSeverityScore(
  accountIds?: string[],
  groupId?: string | null,
): Promise<SeverityScoreData> {
  const params = new URLSearchParams();
  if (groupId) params.set('groupId', groupId);
  else if (accountIds && accountIds.length > 0) params.set('accountIds', accountIds.join(','));
  const response = await fetch(
    apiUrl(`/api/analytics?action=severity-score&${params}`),
    {
      headers: await getApiAuthHeaders(),
    },
  );
  if (!response.ok) throw new Error('Failed to fetch severity score');
  const body = (await response.json()) as { success: boolean } & SeverityScoreData;
  return { accounts: body.accounts, missing: body.missing };
}

/**
 * Per-account 7-day z-score severity vs own 90-day distribution — used by
 * FleetAnomalyGrid to color accent bars and rank worst-first. Accepts a list
 * of account IDs (the rows currently displayed in the grid). React Query
 * caches for 5m so toggling filter chips doesn't re-score.
 */
export function useSeverityScore(
  accountIds?: string[],
  groupId?: string | null,
  enabled: boolean = true,
): SeverityScoreState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;
  const sortedKey = accountIds ? [...accountIds].sort().join(',') : null;
  const queryEnabled = enabled && !!userKey;

  const { data, isPending, isError } = useQuery<SeverityScoreData>({
    queryKey: ['severityScore', userKey, groupId ?? null, sortedKey],
    enabled: queryEnabled,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    queryFn: () => fetchSeverityScore(accountIds, groupId),
  });

  return {
    data: data ?? null,
    isLoading: queryEnabled && isPending,
    hasError: queryEnabled && isError,
    get(accountId: string) {
      return data?.accounts[accountId] ?? null;
    },
  };
}
