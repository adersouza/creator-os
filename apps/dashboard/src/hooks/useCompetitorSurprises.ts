import { useQuery } from '@tanstack/react-query';
import { useAuthUser } from '@/hooks/useAuthUser';
import { getApiAuthHeaders } from '@/lib/apiAuth';
import { apiUrl } from '@/lib/apiUrl';
import { queryKeys } from '@/lib/queryKeys';

export interface CompetitorSurprise {
  id: string;
  competitorId: string;
  competitorUsername: string | null;
  content: string | null;
  permalink: string | null;
  publishedAt: string;
  engagementScore: number;
  medianScore: number;
  multiplier: number;
  likes: number;
  replies: number;
  reposts: number;
  views: number;
}

interface CompetitorSurprisesResponse {
  surprises: CompetitorSurprise[];
  windowHours: number;
  baselineDays: number;
}

interface CompetitorSurprisesState extends CompetitorSurprisesResponse {
  isLoading: boolean;
  hasError: boolean;
}

const EMPTY: CompetitorSurprisesResponse = {
  surprises: [],
  windowHours: 48,
  baselineDays: 30,
};

async function fetchSurprises(): Promise<CompetitorSurprisesResponse> {
  const response = await fetch(apiUrl('/api/analytics?action=competitor-surprises'), {
    headers: await getApiAuthHeaders(),
  });
  if (!response.ok) throw new Error('Failed to fetch competitor surprises');
  const data = (await response.json()) as CompetitorSurprisesResponse;
  return {
    surprises: data.surprises ?? [],
    windowHours: data.windowHours ?? 48,
    baselineDays: data.baselineDays ?? 30,
  };
}

/**
 * Competitor posts outperforming their own baseline — surfaces posts worth
 * reverse-engineering. Read at query time from competitor_top_posts; no
 * dedicated scanner cron.
 */
export function useCompetitorSurprises(): CompetitorSurprisesState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending, isError } = useQuery<CompetitorSurprisesResponse>({
    queryKey: queryKeys.analytics.competitorSurprises(userKey),
    enabled: !!userKey,
    staleTime: 15 * 60 * 1000,
    refetchOnWindowFocus: false,
    queryFn: fetchSurprises,
  });

  return {
    ...(data ?? EMPTY),
    isLoading: !!userKey && isPending,
    hasError: !!userKey && isError,
  };
}
