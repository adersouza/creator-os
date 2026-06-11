import { useQuery } from '@tanstack/react-query';
import { useAuthUser } from '@/hooks/useAuthUser';
import { getApiAuthHeaders } from '@/lib/apiAuth';
import { apiUrl } from '@/lib/apiUrl';

export interface NonFollowerAccount {
  accountId: string;
  username: string | null;
  avgPct: number;
  sampleDays: number;
}

interface NonFollowerResponse {
  fleetAvg: number | null;
  accounts: NonFollowerAccount[];
  periodDays: number;
}

interface NonFollowerState extends NonFollowerResponse {
  isLoading: boolean;
  hasError: boolean;
}

const EMPTY: NonFollowerResponse = { fleetAvg: null, accounts: [], periodDays: 7 };

async function fetchBreakdown(
  periodDays: number,
  accountId: string | null,
): Promise<NonFollowerResponse> {
  const params = new URLSearchParams({ periodDays: String(periodDays) });
  if (accountId) params.set('accountId', accountId);
  const response = await fetch(
    apiUrl(`/api/analytics?action=non-follower-reach-breakdown&${params}`),
    {
      headers: await getApiAuthHeaders(),
    },
  );
  if (!response.ok) throw new Error('Failed to fetch non-follower reach');
  const data = (await response.json()) as NonFollowerResponse;
  return {
    fleetAvg: data.fleetAvg ?? null,
    accounts: data.accounts ?? [],
    periodDays: data.periodDays ?? periodDays,
  };
}

/**
 * Per-account ranking of IG non-follower reach %. Complements the existing
 * useNonFollowerReach hook, which returns fleet-level aggregate with prior-
 * period delta — this one surfaces individual accounts for comparison.
 */
export function useNonFollowerReachLeaders(
  periodDays: number = 7,
  accountId: string | null = null,
): NonFollowerState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending, isError } = useQuery<NonFollowerResponse>({
    queryKey: ['nonFollowerReachLeaders', userKey, periodDays, accountId],
    enabled: !!userKey,
    staleTime: 15 * 60 * 1000,
    refetchOnWindowFocus: false,
    queryFn: () => fetchBreakdown(periodDays, accountId),
  });

  return {
    ...(data ?? EMPTY),
    isLoading: !!userKey && isPending,
    hasError: !!userKey && isError,
  };
}
