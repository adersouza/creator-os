import { useQuery } from '@tanstack/react-query';
import { useAuthUser } from '@/hooks/useAuthUser';
import { getApiAuthHeaders } from '@/lib/apiAuth';
import { apiUrl } from '@/lib/apiUrl';

export type OriginalityPlatform = 'all' | 'instagram' | 'threads';
export type OriginalitySeverity = 'good' | 'warn' | 'crit';

export interface OriginalityPostSummary {
  id: string;
  accountId: string;
  platform: 'threads' | 'instagram';
  username: string | null;
  publishedAt: string | null;
  preview: string;
  reach: number;
}

export interface OriginalityPair {
  similarity: number;
  severity: 'high' | 'medium';
  posts: [OriginalityPostSummary, OriginalityPostSummary];
}

export interface OriginalityAccountRisk {
  accountId: string;
  platform: 'threads' | 'instagram';
  username: string | null;
  riskyPosts: number;
  totalPosts: number;
  highestSimilarity: number;
}

interface OriginalityRiskResponse {
  periodDays: number;
  platform: OriginalityPlatform;
  totalPosts: number;
  riskPostCount: number;
  riskScore: number;
  severity: OriginalitySeverity;
  countdownToThreshold: number;
  highRiskPairs: OriginalityPair[];
  accountRisk: OriginalityAccountRisk[];
  notes?: Record<string, unknown> | undefined;
}

interface OriginalityRiskState extends OriginalityRiskResponse {
  isLoading: boolean;
  hasError: boolean;
}

const EMPTY: OriginalityRiskResponse = {
  periodDays: 30,
  platform: 'all',
  totalPosts: 0,
  riskPostCount: 0,
  riskScore: 0,
  severity: 'good',
  countdownToThreshold: 10,
  highRiskPairs: [],
  accountRisk: [],
  notes: {},
};

async function fetchOriginalityRisk({
  platform,
  accountId,
  accountIds,
  periodDays,
}: {
  platform: OriginalityPlatform;
  accountId?: string | null | undefined;
  accountIds?: string[] | undefined;
  periodDays: number;
}): Promise<OriginalityRiskResponse> {
  const params = new URLSearchParams({
    action: 'originality-risk',
    platform,
    periodDays: String(periodDays),
  });
  if (accountId) params.set('accountId', accountId);
  else if (accountIds && accountIds.length > 0) params.set('accountIds', accountIds.join(','));

  const response = await fetch(apiUrl(`/api/analytics?${params}`), {
    headers: await getApiAuthHeaders(),
  });
  if (!response.ok) throw new Error('Failed to fetch originality risk');

  const data = (await response.json()) as Partial<OriginalityRiskResponse>;
  return {
    periodDays: data.periodDays ?? periodDays,
    platform: data.platform ?? platform,
    totalPosts: data.totalPosts ?? 0,
    riskPostCount: data.riskPostCount ?? 0,
    riskScore: data.riskScore ?? 0,
    severity: data.severity ?? 'good',
    countdownToThreshold: data.countdownToThreshold ?? 10,
    highRiskPairs: data.highRiskPairs ?? [],
    accountRisk: data.accountRisk ?? [],
    notes: data.notes ?? {},
  };
}

export function useOriginalityRisk({
  platform = 'all',
  accountId = null,
  accountIds,
  groupId,
  periodDays = 30,
}: {
  platform?: OriginalityPlatform | undefined;
  accountId?: string | null | undefined;
  accountIds?: string[] | undefined;
  groupId?: string | null | undefined;
  periodDays?: number | undefined;
} = {}): OriginalityRiskState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending, isError } = useQuery<OriginalityRiskResponse>({
    queryKey: ['originalityRisk', userKey, platform, accountId, accountIds?.join(',') ?? null, groupId ?? 'all', periodDays],
    enabled: !!userKey,
    staleTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
    queryFn: () => fetchOriginalityRisk({ platform, accountId, accountIds, periodDays }),
  });

  return {
    ...(data ?? { ...EMPTY, platform, periodDays }),
    isLoading: !!userKey && isPending,
    hasError: !!userKey && isError,
  };
}
