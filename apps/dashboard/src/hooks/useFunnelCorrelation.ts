import { useQuery } from '@tanstack/react-query';
import { useAuthUser } from '@/hooks/useAuthUser';
import { getApiAuthHeaders } from '@/lib/apiAuth';
import { apiUrl } from '@/lib/apiUrl';

export type CorrelationStrength = 'strong' | 'moderate' | 'weak' | 'none';

export interface FunnelDailyPoint {
  date: string;
  views: number;
  postsPublished: number;
  followerChange: number;
  estimatedConversionRate: number;
}

export interface FunnelBestDay {
  date: string;
  rate: number;
  views: number;
  followerChange: number;
}

export interface FunnelSummary {
  avgDailyViews: number;
  avgDailyFollowerChange: number;
  overallConversionRate: number;
  bestConversionDay: FunnelBestDay | null;
  correlationStrength: CorrelationStrength;
}

export interface FunnelConverterPost {
  id: string;
  content: string;
  views: number;
  dayFollowerChange: number;
  publishedAt: string;
  permalink: string | null;
}

export type FunnelMetricKey =
  | 'views'
  | 'reach'
  | 'follows'
  | 'link_taps';

export interface FunnelStep {
  key: FunnelMetricKey;
  label: string;
  value: number;
  rateFromPrevious: number | null;
  available: boolean;
  source: 'account_analytics' | 'follower_history' | 'post_rollup';
}

export interface FunnelCorrelationResponse {
  accountId: string;
  periodDays: number;
  dailyCorrelation: FunnelDailyPoint[];
  funnelSteps?: FunnelStep[] | undefined;
  summary: FunnelSummary;
  topConverterPosts: FunnelConverterPost[];
}

interface FunnelCorrelationState {
  data: FunnelCorrelationResponse | null;
  isLoading: boolean;
  hasError: boolean;
}

async function fetchFunnelCorrelation(
  accountId: string,
  days: number,
): Promise<FunnelCorrelationResponse> {
  const params = new URLSearchParams({ accountId, days: String(days) });
  const response = await fetch(
    apiUrl(`/api/analytics?action=funnel-correlation&${params}`),
    {
      headers: await getApiAuthHeaders(),
    },
  );
  if (!response.ok) {
    let message = 'Failed to fetch funnel correlation';
    if (response.headers.get('content-type')?.includes('application/json')) {
      const body = (await response.json().catch(() => null)) as { error?: string } | null;
      message = body?.error || message;
    }
    throw Object.assign(new Error(message), { status: response.status });
  }
  return (await response.json()) as FunnelCorrelationResponse;
}

/**
 * Views-to-follower conversion correlation for a single account.
 * Uses api/analytics?action=funnel-correlation which returns daily
 * view/follower-change pairs plus Pearson correlation + top converter
 * posts. Backend caps periodDays at 90.
 */
export function useFunnelCorrelation(
  accountId: string | null,
  days: number = 30,
): FunnelCorrelationState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending, isError } = useQuery<FunnelCorrelationResponse>({
    queryKey: ['funnelCorrelation', userKey, accountId, days],
    enabled: !!userKey && !!accountId,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    throwOnError: false,
    queryFn: () => fetchFunnelCorrelation(accountId as string, days),
  });

  return {
    data: data ?? null,
    isLoading: !!userKey && !!accountId && isPending,
    hasError: !!userKey && !!accountId && isError,
  };
}
