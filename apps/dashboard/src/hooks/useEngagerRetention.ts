import { useQuery } from '@tanstack/react-query';
import { useAuthUser } from '@/hooks/useAuthUser';
import { getApiAuthHeaders } from '@/lib/apiAuth';
import { apiUrl } from '@/lib/apiUrl';

export interface Engager {
  username: string;
  engagementCount: number;
  lastInteraction: string | null;
}

export interface EngagerRetentionResponse {
  newCount: number;
  returningCount: number;
  totalUnique: number;
  newPercentage: number;
  returningPercentage: number;
  newEngagers: Engager[];
  returningEngagers: Engager[];
  periodDays: number;
}

interface State {
  data: EngagerRetentionResponse | null;
  isLoading: boolean;
  hasError: boolean;
}

async function fetchEngagerRetention(
  accountId: string,
  periodDays: number,
): Promise<EngagerRetentionResponse> {
  const params = new URLSearchParams({ accountId, periodDays: String(periodDays) });
  const response = await fetch(
    apiUrl(`/api/analytics?action=engager-retention&${params}`),
    {
      headers: await getApiAuthHeaders(),
    },
  );
  if (!response.ok) throw new Error('Failed to fetch engager retention');
  return (await response.json()) as EngagerRetentionResponse;
}

/**
 * New vs returning engagers for one account over the last `periodDays`.
 * Endpoint caps periodDays at 90.
 */
export function useEngagerRetention(
  accountId: string | null,
  periodDays: number = 30,
  accountIds?: string[],
  groupId?: string | null,
): State {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;
  const resolvedAccountId = accountId ?? accountIds?.[0] ?? null;

  const { data, isPending, isError } = useQuery<EngagerRetentionResponse>({
    queryKey: ['engagerRetention', userKey, resolvedAccountId, periodDays, groupId ?? 'all', accountIds?.join(',') ?? null],
    enabled: !!userKey && !!resolvedAccountId,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    queryFn: () => fetchEngagerRetention(resolvedAccountId as string, periodDays),
  });

  return {
    data: data ?? null,
    isLoading: !!userKey && !!resolvedAccountId && isPending,
    hasError: !!userKey && !!resolvedAccountId && isError,
  };
}
