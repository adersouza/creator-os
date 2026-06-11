import { useQuery } from '@tanstack/react-query';
import { useAuthUser } from '@/hooks/useAuthUser';
import { getApiAuthHeaders } from '@/lib/apiAuth';
import { apiUrl } from '@/lib/apiUrl';
import type { AccountScopeValue } from '@/stores/useAccountScopeStore';

export type PillarPlatform = 'all' | 'instagram' | 'threads';

export interface QualityPillar {
  pillar: string;
  postCount: number;
  totalReach: number;
  totalSaves: number;
  totalSends: number;
  qwe: number;
}

interface QualityByPillarResponse {
  pillars: QualityPillar[];
  periodDays: number;
  platform: PillarPlatform;
  thresholdMinPosts: number;
  notes?: {
            threadsReachProxy?: string | undefined;
            igReachField?: string | undefined;
            sendsFormula?: string | undefined;
            savesFormula?: string | undefined;
          } | undefined;
}

interface QualityByPillarState extends QualityByPillarResponse {
  isLoading: boolean;
  hasError: boolean;
}

const EMPTY: QualityByPillarResponse = {
  pillars: [],
  periodDays: 30,
  platform: 'all',
  thresholdMinPosts: 2,
  notes: {},
};

async function fetchQualityByPillar(
  periodDays: number,
  platform: PillarPlatform,
  scopedAccount: AccountScopeValue | null,
  accountIds?: string[],
): Promise<QualityByPillarResponse> {
  const params = new URLSearchParams({
    action: 'quality-by-pillar',
    periodDays: String(periodDays),
    platform,
  });
  if (scopedAccount) {
    params.set('accountId', scopedAccount.id);
    params.set('platform', scopedAccount.platform);
  } else if (accountIds && accountIds.length > 0) {
    params.set('accountIds', accountIds.join(','));
  }
  const response = await fetch(apiUrl(`/api/analytics?${params}`), {
    headers: await getApiAuthHeaders(),
  });
  if (!response.ok) {
    let message = 'Failed to fetch quality by pillar';
    if (response.headers.get('content-type')?.includes('application/json')) {
      const body = (await response.json().catch(() => null)) as { error?: string } | null;
      message = body?.error || message;
    }
    throw Object.assign(new Error(message), { status: response.status });
  }
  const data = (await response.json()) as Partial<QualityByPillarResponse>;
  return {
    pillars: data.pillars ?? [],
    periodDays: data.periodDays ?? periodDays,
    platform: data.platform ?? platform,
    thresholdMinPosts: data.thresholdMinPosts ?? 2,
    notes: data.notes ?? {},
  };
}

export function useQualityByPillar(
  periodDays = 30,
  platform: PillarPlatform = 'all',
  scopedAccount: AccountScopeValue | null = null,
  accountIds?: string[],
  groupId?: string | null,
): QualityByPillarState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending, isError } = useQuery<QualityByPillarResponse>({
    queryKey: ['qualityByPillar', userKey, periodDays, platform, scopedAccount?.id ?? 'fleet', groupId ?? 'all', accountIds?.join(',') ?? null],
    enabled: !!userKey,
    staleTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
    throwOnError: false,
    queryFn: () => fetchQualityByPillar(periodDays, platform, scopedAccount, accountIds),
  });

  return {
    ...(data ?? { ...EMPTY, periodDays, platform }),
    isLoading: !!userKey && isPending,
    hasError: !!userKey && isError,
  };
}
