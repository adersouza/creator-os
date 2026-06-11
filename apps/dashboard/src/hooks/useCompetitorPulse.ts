import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';
import { queryKeys } from '@/lib/queryKeys';

export interface CompetitorPulseState {
  /** How many competitors the user is tracking. */
  trackedCount: number;
  /** Median engagement_rate across the user's tracked competitors (0–1 decimal). null when trackedCount === 0. */
  medianRate: number | null;
  /** P95 engagement_rate across competitors (0–1 decimal). */
  p95Rate: number | null;
  /** Sorted array of all competitor engagement_rate values (for percentile computation by the widget). */
  ratesDescending: number[];
  isLoading: boolean;
}

const EMPTY: Omit<CompetitorPulseState, 'isLoading'> = {
  trackedCount: 0,
  medianRate: null,
  p95Rate: null,
  ratesDescending: [],
};

/**
 * Reads the user's `competitors` rows and rolls up engagement_rate into median + P95
 * so the Overview's Competitor Pulse widget can show where their EQS sits in the pack.
 */
export function useCompetitorPulse(): CompetitorPulseState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending } = useQuery({
    queryKey: queryKeys.analytics.competitorPulse(userKey),
    enabled: !!userKey,
    queryFn: async () => {
      const user = (await supabase.auth.getUser()).data.user;
      if (!user) return EMPTY;

      const { data, error } = await supabase
        .from('competitors')
        .select('engagement_rate')
        .eq('user_id', user.id);

      if (error) throw error;

      const rates = (data ?? [])
        .map((r) => (typeof r.engagement_rate === 'number' ? r.engagement_rate : null))
        .filter((v): v is number => v !== null && v > 0)
        .sort((a, b) => b - a);

      const trackedCount = data?.length ?? 0;

      if (rates.length === 0) {
        return { ...EMPTY, trackedCount };
      }

      const median = rates[Math.floor(rates.length / 2)];
      const p95Index = Math.max(0, Math.floor(rates.length * 0.05));
      const p95 = rates[p95Index];

      return {
        trackedCount,
      medianRate: median ?? null,
      p95Rate: p95 ?? null,
        ratesDescending: rates,
      };
    },
  });

  return {
    ...(data ?? EMPTY),
    isLoading: !!userKey && isPending,
  };
}

/**
 * Given the user's engagement rate (0–1) and a sorted (descending) array of competitor
 * rates, return the user's percentile rank (0–100). Higher is better.
 */
export function rankPercentile(myRate: number, ratesDescending: number[]): number {
  if (!ratesDescending.length) return 0;
  let below = 0;
  for (const r of ratesDescending) {
    if (myRate >= r) below += 1;
  }
  return Math.round((below / ratesDescending.length) * 100);
}
