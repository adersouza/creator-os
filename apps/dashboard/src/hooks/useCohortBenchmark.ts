import { useQuery } from '@tanstack/react-query';
import { useAuthUser } from '@/hooks/useAuthUser';
import { getApiAuthHeaders } from '@/lib/apiAuth';
import { apiUrl } from '@/lib/apiUrl';

export type CohortPlatform = 'threads' | 'instagram';
export type FollowerTier = '0-1K' | '1K-5K' | '5K-10K' | '10K-50K' | '50K+';
export type CohortNiche =
  | 'ofm'
  | 'fitness'
  | 'beauty'
  | 'lifestyle'
  | 'business'
  | 'finance'
  | 'tech'
  | 'uncategorized';

export type CohortMetricResponse =
  | { status: 'locked' }
  | { status: 'suppressed'; reason: string; account_count: number; user_count: number }
  | {
      status: 'workspace_baseline';
      p25: number | null;
      p50: number | null;
      p75: number | null;
      p90: number | null;
      mean: number | null;
      account_count: number;
      user_count: number;
      snapshot_date: string;
    }
  | {
      status: 'median_only';
      p50: number | null;
      mean: number | null;
      account_count: number;
      user_count: number;
      snapshot_date: string;
    }
  | {
      status: 'ok';
      p25: number | null;
      p50: number | null;
      p75: number | null;
      p90: number | null;
      mean: number | null;
      stddev: number | null;
      account_count: number;
      user_count: number;
      snapshot_date: string;
    };

interface CohortResponse {
  platform: CohortPlatform;
  follower_tier: FollowerTier;
  niche: CohortNiche;
  resolved_from?: string | undefined;
  metrics: Record<string, CohortMetricResponse>;
}

interface Args {
  platform: CohortPlatform;
  followerTier?: FollowerTier | undefined;
  niche?: CohortNiche | undefined;
  metrics: string[];
  enabled?: boolean | undefined;
}

async function fetchCohortBenchmark({
  platform,
  followerTier,
  niche,
  metrics,
}: Args): Promise<CohortResponse> {
  const params = new URLSearchParams({
    action: 'cohort-benchmarks',
    platform,
    metrics: metrics.join(','),
  });
  if (followerTier) params.set('follower_tier', followerTier);
  if (niche) params.set('niche', niche);
  const response = await fetch(apiUrl(`/api/analytics?${params}`), {
    headers: await getApiAuthHeaders(),
  });
  if (!response.ok) throw new Error('Failed to fetch cohort benchmarks');
  const body = (await response.json()) as { success: boolean } & CohortResponse;
  return {
    platform: body.platform,
    follower_tier: body.follower_tier,
    niche: body.niche,
    resolved_from: body.resolved_from,
    metrics: body.metrics,
  };
}

/**
 * Per-bucket anonymized cohort benchmark (follower-band × niche). The handler
 * returns a locked/suppressed/median_only/ok status per metric; this hook is
 * a thin Tanstack Query wrapper with a 30-minute stale window that matches
 * the daily-ish refresh cadence on the server side.
 */
export function useCohortBenchmark(args: Args) {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;
  const metricKey = [...args.metrics].sort().join(',');
  const enabled =
    !!userKey && (args.enabled ?? true) && args.metrics.length > 0;

  const { data, isPending, isError } = useQuery<CohortResponse>({
    queryKey: [
      'cohortBenchmark',
      userKey,
      args.platform,
      args.followerTier ?? 'auto-tier',
      args.niche ?? 'auto-niche',
      metricKey,
    ],
    enabled,
    staleTime: 30 * 60 * 1000,
    refetchOnWindowFocus: false,
    queryFn: () => fetchCohortBenchmark(args),
  });

  return {
    data: data ?? null,
    isLoading: enabled && isPending,
    hasError: enabled && isError,
  };
}
