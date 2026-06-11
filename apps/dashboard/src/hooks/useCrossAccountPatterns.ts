import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';
import { apiUrl } from '@/lib/apiUrl';
import { queryKeys } from '@/lib/queryKeys';

export interface CrossAccountPattern {
  topic: string;
  accountCount: number;
  posts: number;
  avgReach: number;
  lift: number;
}

interface CrossAccountPatternsResponse {
  patterns: CrossAccountPattern[];
  periodDays: number;
  fleetAvgReach?: number | undefined;
  reason?: string | undefined;
}

interface CrossAccountPatternsState extends CrossAccountPatternsResponse {
  isLoading: boolean;
  hasError: boolean;
}

const EMPTY: CrossAccountPatternsResponse = { patterns: [], periodDays: 30 };

async function fetchPatterns(): Promise<CrossAccountPatternsResponse> {
  const session = (await supabase.auth.getSession()).data.session;
  const response = await fetch(apiUrl('/api/analytics?action=cross-account-patterns'), {
    headers: session?.access_token
      ? { Authorization: `Bearer ${session.access_token}` }
      : {},
  });
  if (!response.ok) throw new Error('Failed to fetch cross-account patterns');
  const data = (await response.json()) as CrossAccountPatternsResponse;
  return {
    patterns: data.patterns ?? [],
    periodDays: data.periodDays ?? 30,
    fleetAvgReach: data.fleetAvgReach,
    reason: data.reason,
  };
}

/**
 * Topics lifting across ≥2 accounts in the user's fleet. Cheap MVP —
 * post.topic_tag + reach only, no audio clustering yet.
 */
export function useCrossAccountPatterns(): CrossAccountPatternsState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending, isError } = useQuery<CrossAccountPatternsResponse>({
    queryKey: queryKeys.analytics.crossAccountPatterns(userKey),
    enabled: !!userKey,
    staleTime: 30 * 60 * 1000,
    refetchOnWindowFocus: false,
    queryFn: fetchPatterns,
  });

  return {
    ...(data ?? EMPTY),
    isLoading: !!userKey && isPending,
    hasError: !!userKey && isError,
  };
}
