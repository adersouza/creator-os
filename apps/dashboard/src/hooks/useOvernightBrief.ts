import { useQuery } from '@tanstack/react-query';
import { useAuthUser } from '@/hooks/useAuthUser';
import { getApiAuthHeaders } from '@/lib/apiAuth';
import { apiUrl } from '@/lib/apiUrl';

export interface OvernightBriefMove {
  label: string;
  reason: string;
  route: string;
  severity: 'good' | 'warn' | 'critical';
}

export interface OvernightBriefAnomaly {
  account: string;
  metric: string;
  direction: 'up' | 'down';
  severity: 'low' | 'medium' | 'high' | 'critical';
}

export interface OvernightBrief {
  id: string;
  narrative: string;
  moves: OvernightBriefMove[];
  anomalies: OvernightBriefAnomaly[];
  generatedAt: string;
  windowStart: string;
  windowEnd: string;
  aiModel: string | null;
}

interface OvernightBriefResponse {
  brief: OvernightBrief | null;
  fallback: 'live' | null;
}

interface OvernightBriefState {
  brief: OvernightBrief | null;
  fallback: 'live' | null;
  isLoading: boolean;
  hasError: boolean;
}

async function fetchOvernightBrief(): Promise<OvernightBriefResponse> {
  const response = await fetch(apiUrl('/api/analytics?action=overnight-brief'), {
    headers: await getApiAuthHeaders(),
  });
  if (!response.ok) {
    // Treat as no brief — widget falls back to live compute.
    return { brief: null, fallback: 'live' };
  }
  const data = (await response.json()) as OvernightBriefResponse;
  return { brief: data.brief ?? null, fallback: data.fallback ?? null };
}

/**
 * Reads the latest cron-generated overnight brief for the logged-in user.
 * When no fresh brief exists (new user, cron skipped, etc.), `fallback = 'live'`
 * — the caller renders its live-compute path. 5-minute staleTime because briefs
 * regenerate once per day; short enough that a manual cron trigger is visible
 * within a refresh cycle.
 */
export function useOvernightBrief(): OvernightBriefState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending, isError } = useQuery<OvernightBriefResponse>({
    queryKey: ['overnightBrief', userKey],
    enabled: !!userKey,
    staleTime: 5 * 60 * 1000,
    // Briefs refresh once per day at 1:55 AM — window focus shouldn't trigger
    // refetches; the 5-minute staleTime already covers recency.
    refetchOnWindowFocus: false,
    queryFn: fetchOvernightBrief,
  });

  return {
    brief: data?.brief ?? null,
    fallback: data?.fallback ?? null,
    isLoading: isPending,
    hasError: isError,
  };
}
