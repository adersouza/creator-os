import { useQuery } from '@tanstack/react-query';
import { useAuthUser } from '@/hooks/useAuthUser';
import { getApiAuthHeaders } from '@/lib/apiAuth';
import { apiUrl } from '@/lib/apiUrl';

type ReachAnomalyStatus =
  | 'insufficient_data'
  | 'anomaly'
  | 'concerning'
  | 'above_average'
  | 'normal';

export interface ReachAnomalyAccount {
  accountId: string;
  username: string;
  status: ReachAnomalyStatus;
  message: string | null;
  reachChangePercent: number | null;
  recentAvg: number | null;
  baselineAvg: number | null;
  recentPostCount: number;
  baselinePostCount: number;
  dataSource: 'post_metric_history_24h' | 'posts_latest_snapshot' | null;
  followerTrend: 'flat' | 'growing' | 'declining' | null;
  followerChange: number | null;
  isLikelyShadowban: boolean;
  verdict: string | null;
}

interface ReachAnomaliesResponse {
  accounts: ReachAnomalyAccount[];
  total: number;
  concerning: number;
  anomalous: number;
  sourceAccounts: number;
}

interface ReachAnomaliesState extends ReachAnomaliesResponse {
  isLoading: boolean;
  hasError: boolean;
}

const EMPTY: ReachAnomaliesResponse = {
  accounts: [],
  total: 0,
  concerning: 0,
  anomalous: 0,
  sourceAccounts: 0,
};

async function fetchReachAnomalies(limit: number): Promise<ReachAnomaliesResponse> {
  const params = new URLSearchParams({
    action: 'reach-anomalies',
    limit: String(limit),
  });
  const response = await fetch(apiUrl(`/api/analytics?${params}`), {
    headers: await getApiAuthHeaders(),
  });
  if (!response.ok) throw new Error('Failed to fetch reach anomalies');
  const data = (await response.json()) as ReachAnomaliesResponse;
  return {
    accounts: data.accounts ?? [],
    total: data.total ?? 0,
    concerning: data.concerning ?? 0,
    anomalous: data.anomalous ?? 0,
    sourceAccounts: data.sourceAccounts ?? 0,
  };
}

/**
 * Per-Threads account reach anomaly rollup. The backend compares recent posts
 * from the last 3 days against the 4-14 day baseline, preferring first-24h
 * post_metric_history snapshots when available.
 */
export function useReachAnomalies(limit: number = 50): ReachAnomaliesState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending, isError } = useQuery<ReachAnomaliesResponse>({
    queryKey: ['reachAnomalies', userKey, limit],
    enabled: !!userKey,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    queryFn: () => fetchReachAnomalies(limit),
  });

  return {
    ...(data ?? EMPTY),
    isLoading: !!userKey && isPending,
    hasError: !!userKey && isError,
  };
}
