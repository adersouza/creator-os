import { useQuery } from '@tanstack/react-query';
import { useAuthUser } from '@/hooks/useAuthUser';
import { getApiAuthHeaders } from '@/lib/apiAuth';
import { apiUrl } from '@/lib/apiUrl';

export type FleetHealthBucket = 'crit' | 'warn' | 'healthy';

export interface FleetAccountHealth {
  accountId: string;
  username: string | null;
  platform: 'threads' | 'instagram';
  bucket: FleetHealthBucket;
  reason: string | null;
  lastSyncedAt: string | null;
  groupId: string | null;
  tokenDaysLeft: number | null;
}

interface FleetHealthAccountsResponse {
  accounts: FleetAccountHealth[];
  summary: {
    total: number;
    crit: number;
    warn: number;
    healthy: number;
    minTokenDaysLeft: number | null;
  };
}

interface FleetHealthAccountsState extends FleetHealthAccountsResponse {
  isLoading: boolean;
  hasError: boolean;
}

const EMPTY: FleetHealthAccountsResponse = {
  accounts: [],
  summary: { total: 0, crit: 0, warn: 0, healthy: 0, minTokenDaysLeft: null },
};

async function fetchAccounts(limit: number): Promise<FleetHealthAccountsResponse> {
  const params = new URLSearchParams({ limit: String(limit) });
  const response = await fetch(apiUrl(`/api/analytics?action=fleet-health-accounts&${params}`), {
    headers: await getApiAuthHeaders(),
  });
  if (!response.ok) throw new Error('Failed to fetch fleet health accounts');
  const data = (await response.json()) as FleetHealthAccountsResponse;
  const summary = data.summary ?? EMPTY.summary;
  return {
    accounts: data.accounts ?? [],
    summary: {
      total: summary.total ?? 0,
      crit: summary.crit ?? 0,
      warn: summary.warn ?? 0,
      healthy: summary.healthy ?? 0,
      minTokenDaysLeft: summary.minTokenDaysLeft ?? null,
    },
  };
}

/**
 * Per-account fleet health classification — complements the fleet-level
 * get_fleet_health RPC. Sorted worst-first (crit → warn → healthy) so
 * operators see what to fix before the rest of the list.
 */
export function useFleetHealthAccounts(limit: number = 10): FleetHealthAccountsState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending, isError } = useQuery<FleetHealthAccountsResponse>({
    queryKey: ['fleetHealthAccounts', userKey, limit],
    enabled: !!userKey,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    queryFn: () => fetchAccounts(limit),
  });

  return {
    ...(data ?? EMPTY),
    isLoading: !!userKey && isPending,
    hasError: !!userKey && isError,
  };
}
