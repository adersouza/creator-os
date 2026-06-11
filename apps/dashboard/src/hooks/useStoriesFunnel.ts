import { useQuery } from '@tanstack/react-query';
import { useAuthUser } from '@/hooks/useAuthUser';
import { getApiAuthHeaders } from '@/lib/apiAuth';
import { apiUrl } from '@/lib/apiUrl';
import type { AccountScopeValue } from '@/stores/useAccountScopeStore';

export interface StoryFunnelFrame {
  postId: string;
  publishedAt: string;
  views: number;
  reach: number;
  tapsForward: number;
  tapsBack: number;
  exits: number;
  replies: number;
  retentionPct: number;
  dropoffPct: number;
}

export interface StoryFunnelSequence {
  accountId: string;
  username: string | null;
  startedAt: string;
  frameCount: number;
  frames: StoryFunnelFrame[];
  totals: {
    views: number;
    reach: number;
    tapsForward: number;
    tapsBack: number;
    exits: number;
    replies: number;
  };
  completionPct: number;
  exitFramePeak: number | null;
}

interface StoriesFunnelResponse {
  sequences: StoryFunnelSequence[];
  periodDays: number;
  notes?: Record<string, unknown> | undefined;
}

interface StoriesFunnelState extends StoriesFunnelResponse {
  isLoading: boolean;
  hasError: boolean;
}

const EMPTY: StoriesFunnelResponse = {
  sequences: [],
  periodDays: 14,
  notes: {},
};

async function fetchStoriesFunnel(
  periodDays: number,
  scopedAccount: AccountScopeValue | null,
  accountIds?: string[],
): Promise<StoriesFunnelResponse> {
  const params = new URLSearchParams({
    action: 'stories-funnel',
    periodDays: String(periodDays),
  });
  if (scopedAccount) {
    params.set('accountId', scopedAccount.id);
  } else if (accountIds && accountIds.length > 0) {
    params.set('accountIds', accountIds.join(','));
  }
  const response = await fetch(apiUrl(`/api/analytics?${params}`), {
    headers: await getApiAuthHeaders(),
  });
  if (!response.ok) throw new Error('Failed to fetch stories funnel');
  const data = (await response.json()) as Partial<StoriesFunnelResponse>;
  return {
    sequences: data.sequences ?? [],
    periodDays: data.periodDays ?? periodDays,
    notes: data.notes ?? {},
  };
}

export function useStoriesFunnel(
  periodDays = 14,
  scopedAccount: AccountScopeValue | null = null,
  accountIds?: string[],
  groupId?: string | null,
): StoriesFunnelState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending, isError } = useQuery<StoriesFunnelResponse>({
    queryKey: ['storiesFunnel', userKey, periodDays, scopedAccount?.id ?? 'fleet', groupId ?? 'all', accountIds?.join(',') ?? null],
    enabled: !!userKey,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    queryFn: () => fetchStoriesFunnel(periodDays, scopedAccount, accountIds),
  });

  return {
    ...(data ?? EMPTY),
    isLoading: !!userKey && isPending,
    hasError: !!userKey && isError,
  };
}
