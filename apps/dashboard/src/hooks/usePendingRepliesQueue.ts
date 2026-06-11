import { useQuery } from '@tanstack/react-query';
import { useAuthUser } from '@/hooks/useAuthUser';
import { getApiAuthHeaders } from '@/lib/apiAuth';
import { apiUrl } from '@/lib/apiUrl';

export interface PendingRepliesAccount {
  accountId: string;
  username: string | null;
  pending: number;
  needsReview: number;
  total: number;
  topReason: string | null;
}

interface PendingRepliesResponse {
  accounts: PendingRepliesAccount[];
  total: number;
  needsReview: number;
  pending: number;
}

interface PendingRepliesState extends PendingRepliesResponse {
  isLoading: boolean;
  hasError: boolean;
}

const EMPTY: PendingRepliesResponse = { accounts: [], total: 0, needsReview: 0, pending: 0 };

async function fetchQueue(accountId: string | null): Promise<PendingRepliesResponse> {
  const params = new URLSearchParams();
  if (accountId) params.set('accountId', accountId);
  const qs = params.toString();
  const url = apiUrl(`/api/analytics?action=pending-replies-queue${qs ? `&${qs}` : ''}`);
  const response = await fetch(url, {
    headers: await getApiAuthHeaders(),
  });
  if (!response.ok) throw new Error('Failed to fetch pending replies');
  const data = (await response.json()) as PendingRepliesResponse;
  return {
    accounts: data.accounts ?? [],
    total: data.total ?? 0,
    needsReview: data.needsReview ?? 0,
    pending: data.pending ?? 0,
  };
}

/**
 * Fleet rollup of auto_reply_queue — pending replies awaiting the auto-reply
 * worker plus needs-review items flagged by safety rules. Threads-only.
 */
export function usePendingRepliesQueue(
  accountId: string | null = null,
): PendingRepliesState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending, isError } = useQuery<PendingRepliesResponse>({
    queryKey: ['pendingRepliesQueue', userKey, accountId],
    enabled: !!userKey,
    staleTime: 2 * 60 * 1000,
    refetchOnWindowFocus: false,
    queryFn: () => fetchQueue(accountId).catch(() => EMPTY),
  });

  return {
    ...(data ?? EMPTY),
    isLoading: !!userKey && isPending,
    hasError: !!userKey && isError,
  };
}
