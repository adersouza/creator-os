import { useQuery } from '@tanstack/react-query';
import { useAuthUser } from '@/hooks/useAuthUser';
import { getApiAuthHeaders } from '@/lib/apiAuth';
import { apiUrl } from '@/lib/apiUrl';

export type StrikesPlatform = 'all' | 'instagram' | 'threads';
export type StrikeSeverity = 'good' | 'warn' | 'crit';

export interface AccountStrikes {
  accountId: string;
  platform: 'threads' | 'instagram';
  username: string | null;
  strikes: number;
  breakdown: {
    shadowban: number;
    chronicTokenFailures: number;
    anomalies: number;
  };
}

interface StrikesCountResponse {
  totalStrikes: number;
  ringValue: number;
  severity: StrikeSeverity;
  accountsWithStrikes: number;
  totalAccounts: number;
  perAccount: AccountStrikes[];
  periodDays: number;
  notes?: Record<string, unknown> | undefined;
}

interface StrikesCountState extends StrikesCountResponse {
  isLoading: boolean;
  hasError: boolean;
}

const EMPTY: StrikesCountResponse = {
  totalStrikes: 0,
  ringValue: 0,
  severity: 'good',
  accountsWithStrikes: 0,
  totalAccounts: 0,
  perAccount: [],
  periodDays: 90,
  notes: {},
};

async function fetchStrikesCount({
  platform,
  accountId,
  periodDays,
}: {
  platform: StrikesPlatform;
  accountId?: string | null | undefined;
  periodDays: number;
}): Promise<StrikesCountResponse> {
  const params = new URLSearchParams({
    action: 'strikes-count',
    periodDays: String(periodDays),
    platform,
  });
  if (accountId) params.set('accountId', accountId);

  const response = await fetch(apiUrl(`/api/analytics?${params}`), {
    headers: await getApiAuthHeaders(),
  });
  if (!response.ok) throw new Error('Failed to fetch strikes count');

  const data = (await response.json()) as Partial<StrikesCountResponse>;
  return {
    totalStrikes: data.totalStrikes ?? 0,
    ringValue: data.ringValue ?? data.accountsWithStrikes ?? data.totalStrikes ?? 0,
    severity: data.severity ?? 'good',
    accountsWithStrikes: data.accountsWithStrikes ?? 0,
    totalAccounts: data.totalAccounts ?? 0,
    perAccount: data.perAccount ?? [],
    periodDays: data.periodDays ?? periodDays,
    notes: data.notes ?? {},
  };
}

export function useStrikesCount({
  platform = 'all',
  accountId = null,
  periodDays = 90,
}: {
  platform?: StrikesPlatform | undefined;
  accountId?: string | null | undefined;
  periodDays?: number | undefined;
} = {}): StrikesCountState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending, isError } = useQuery<StrikesCountResponse>({
    queryKey: ['strikesCount', userKey, platform, accountId, periodDays],
    enabled: !!userKey,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    queryFn: () => fetchStrikesCount({ platform, accountId, periodDays }),
  });

  return {
    ...(data ?? { ...EMPTY, platform, periodDays }),
    isLoading: !!userKey && isPending,
    hasError: !!userKey && isError,
  };
}
