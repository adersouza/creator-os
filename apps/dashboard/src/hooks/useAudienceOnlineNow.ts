import { useQuery } from '@tanstack/react-query';
import { useAuthUser } from '@/hooks/useAuthUser';
import { getApiAuthHeaders } from '@/lib/apiAuth';
import { apiUrl } from '@/lib/apiUrl';

interface AudienceOnlineResponse {
  hourlyUtc: number[];
  accountCount: number;
}

interface AudienceOnlineState extends AudienceOnlineResponse {
  isLoading: boolean;
  hasError: boolean;
}

const EMPTY: AudienceOnlineResponse = { hourlyUtc: [], accountCount: 0 };

async function fetchHourly(accountId: string | null): Promise<AudienceOnlineResponse> {
  const params = new URLSearchParams();
  if (accountId) params.set('accountId', accountId);
  const qs = params.toString();
  const url = apiUrl(`/api/analytics?action=audience-online-now${qs ? `&${qs}` : ''}`);
  const response = await fetch(url, {
    headers: await getApiAuthHeaders(),
  });
  if (!response.ok) throw new Error('Failed to fetch online followers');
  const data = (await response.json()) as AudienceOnlineResponse;
  return {
    hourlyUtc: data.hourlyUtc ?? [],
    accountCount: data.accountCount ?? 0,
  };
}

/**
 * IG audience-online-now — 24 hourly buckets in UTC. Caller shifts into
 * the user's local tz for display.
 */
export function useAudienceOnlineNow(accountId: string | null = null): AudienceOnlineState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending, isError } = useQuery<AudienceOnlineResponse>({
    queryKey: ['audienceOnlineNow', userKey, accountId],
    enabled: !!userKey,
    staleTime: 30 * 60 * 1000,
    refetchOnWindowFocus: false,
    queryFn: () => fetchHourly(accountId),
  });

  return {
    ...(data ?? EMPTY),
    isLoading: !!userKey && isPending,
    hasError: !!userKey && isError,
  };
}
