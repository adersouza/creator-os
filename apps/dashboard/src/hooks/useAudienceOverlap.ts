import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';

export interface OverlapAccount {
  id: string;
  label: string;
  uniqueEngagers: number;
}

export interface OverlapEngager {
  username: string;
  accountIds: string[];
  totalInteractions: number;
}

export interface AudienceOverlapResponse {
  accounts: OverlapAccount[];
  overlaps: OverlapEngager[];
  overlapCount: number;
  overlapPercentage: number;
}

interface State {
  data: AudienceOverlapResponse | null;
  isLoading: boolean;
  hasError: boolean;
}

async function fetchAudienceOverlap(accountIds: string[]): Promise<AudienceOverlapResponse> {
  const session = (await supabase.auth.getSession()).data.session;
  const params = new URLSearchParams({ accountIds: accountIds.join(',') });
  const response = await fetch(
    `/api/analytics?action=audience-overlap&${params}`,
    {
      headers: session?.access_token
        ? { Authorization: `Bearer ${session.access_token}` }
        : {},
    },
  );
  if (!response.ok) throw new Error('Failed to fetch audience overlap');
  return (await response.json()) as AudienceOverlapResponse;
}

/**
 * Pairwise overlap of repeat engagers between accounts in scope. The endpoint
 * caps at 20 accounts; the hook trims the input list before sending.
 *
 * Returns null until at least 2 accounts are passed (single-account scope
 * has nothing to compare).
 */
export function useAudienceOverlap(accountIds: string[], groupId?: string | null): State {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;
  const trimmed = accountIds.slice(0, 20);
  const eligible = trimmed.length >= 2;

  const { data, isPending, isError } = useQuery<AudienceOverlapResponse>({
    queryKey: ['audienceOverlap', userKey, groupId ?? 'all', trimmed.join(',')],
    enabled: !!userKey && eligible,
    staleTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
    queryFn: () => fetchAudienceOverlap(trimmed),
  });

  return {
    data: data ?? null,
    isLoading: !!userKey && eligible && isPending,
    hasError: !!userKey && eligible && isError,
  };
}
