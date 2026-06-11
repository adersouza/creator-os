import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';

export interface CompetitorBenchmarkResponse {
  userFollowers: number;
  userRate: number;
  peerCount: number;
  peerBand?: { low: number; high: number } | undefined;
  percentile: number | null;
  peerP50: number;
  peerP75: number;
  peerP90: number;
}

interface State {
  data: CompetitorBenchmarkResponse | null;
  isLoading: boolean;
  hasError: boolean;
}

async function fetchCompetitorBenchmark(
  accountId: string,
  platform: 'threads' | 'instagram',
  bandWidth: number,
): Promise<CompetitorBenchmarkResponse> {
  const session = (await supabase.auth.getSession()).data.session;
  const params = new URLSearchParams({
    accountId,
    platform,
    bandWidth: String(bandWidth),
  });
  const response = await fetch(
    `/api/analytics?action=competitor-benchmark&${params}`,
    {
      headers: session?.access_token
        ? { Authorization: `Bearer ${session.access_token}` }
        : {},
    },
  );
  if (!response.ok) throw new Error('Failed to fetch competitor benchmark');
  return (await response.json()) as CompetitorBenchmarkResponse;
}

/**
 * Snapshot percentile of one account's normalized 7d engagement rate against
 * the peer pool inside a follower-size band (default ±50%). Wraps
 * api/analytics?action=competitor-benchmark.
 */
export function useCompetitorBenchmark(
  accountId: string | null,
  platform: 'threads' | 'instagram',
  bandWidth: number = 0.5,
): State {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending, isError } = useQuery<CompetitorBenchmarkResponse>({
    queryKey: ['competitorBenchmark', userKey, accountId, platform, bandWidth],
    enabled: !!userKey && !!accountId,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    queryFn: () => fetchCompetitorBenchmark(accountId as string, platform, bandWidth),
  });

  return {
    data: data ?? null,
    isLoading: !!userKey && !!accountId && isPending,
    hasError: !!userKey && !!accountId && isError,
  };
}
