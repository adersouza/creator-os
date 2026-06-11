import { useQuery } from '@tanstack/react-query';
import { useAuthUser } from '@/hooks/useAuthUser';
import { getApiAuthHeaders } from '@/lib/apiAuth';
import { apiUrl } from '@/lib/apiUrl';
import type { AccountScopeValue } from '@/stores/useAccountScopeStore';

export type HookLiftPlatform = 'all' | 'instagram' | 'threads';

export interface HookClassLiftRow {
  hookClass: string;
  postCount: number;
  totalReach: number;
  avgReach: number;
  lift: number;
}

interface HookClassLiftResponse {
  hooks: HookClassLiftRow[];
  fleetAvgReach: number;
  fleetPostCount: number;
  periodDays: number;
  platform: HookLiftPlatform;
  thresholdMinPosts: number;
  thresholdMinConfidence: number;
  notes?: {
            reachField?: string | undefined;
          } | undefined;
}

interface HookClassLiftState extends HookClassLiftResponse {
  isLoading: boolean;
  hasError: boolean;
}

const EMPTY: HookClassLiftResponse = {
  hooks: [],
  fleetAvgReach: 0,
  fleetPostCount: 0,
  periodDays: 30,
  platform: 'all',
  thresholdMinPosts: 3,
  thresholdMinConfidence: 0.5,
  notes: {},
};

async function fetchHookClassLift(
  periodDays: number,
  platform: HookLiftPlatform,
  scopedAccount: AccountScopeValue | null,
  accountIds?: string[],
): Promise<HookClassLiftResponse> {
  const params = new URLSearchParams({
    action: 'hook-class-lift',
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
  if (!response.ok) throw new Error('Failed to fetch hook-class lift');

  const data = (await response.json()) as Partial<HookClassLiftResponse>;
  return {
    hooks: data.hooks ?? [],
    fleetAvgReach: data.fleetAvgReach ?? 0,
    fleetPostCount: data.fleetPostCount ?? 0,
    periodDays: data.periodDays ?? periodDays,
    platform: data.platform ?? platform,
    thresholdMinPosts: data.thresholdMinPosts ?? 3,
    thresholdMinConfidence: data.thresholdMinConfidence ?? 0.5,
    notes: data.notes ?? {},
  };
}

export function useHookClassLift(
  periodDays = 30,
  platform: HookLiftPlatform = 'all',
  scopedAccount: AccountScopeValue | null = null,
  accountIds?: string[],
  groupId?: string | null,
): HookClassLiftState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending, isError } = useQuery<HookClassLiftResponse>({
    queryKey: ['hookClassLift', userKey, periodDays, platform, scopedAccount?.id ?? 'fleet', groupId ?? 'all', accountIds?.join(',') ?? null],
    enabled: !!userKey,
    staleTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
    queryFn: () => fetchHookClassLift(periodDays, platform, scopedAccount, accountIds),
  });

  return {
    ...(data ?? { ...EMPTY, periodDays, platform }),
    isLoading: !!userKey && isPending,
    hasError: !!userKey && isError,
  };
}
