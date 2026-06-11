// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';
import { queryKeys } from '@/lib/queryKeys';

/**
 * Fleet-level profile visits over the last `periodDays`. Sums
 * posts.ig_profile_visits (synced via Meta v25 profile_activity insight
 * with action_type breakdown) for all published IG posts in the window,
 * and compares to the prior equal-length window for a WoW delta.
 *
 * Top 10 Creator Dashboard KPI #7 per the 2026 research.
 */
export interface FleetProfileVisitsState {
  total: number;
  prior: number;
  deltaPct: number | null;
  // Daily breakdown for the sparkline — oldest → newest, length = periodDays.
  daily: number[];
  isLoading: boolean;
  hasError: boolean;
}

const DAY_MS = 24 * 60 * 60 * 1000;

export function useFleetProfileVisits(periodDays = 7): FleetProfileVisitsState {
  const authUser = useAuthUser();
  const userKey = authUser?.id ?? null;

  const { data, isPending, isError } = useQuery({
    queryKey: queryKeys.fleet.profileVisits(userKey, periodDays),
    enabled: !!userKey,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    queryFn: async () => {
      if (!userKey) {
        return { total: 0, prior: 0, deltaPct: null as number | null, daily: [] };
      }

      const now = Date.now();
      const currentStart = now - periodDays * DAY_MS;
      const priorStart = now - 2 * periodDays * DAY_MS;

      const { data: posts, error } = await supabase
        .from('posts')
        .select('ig_profile_visits, published_at')
        .eq('user_id', userKey)
        .eq('platform', 'instagram')
        .eq('status', 'published')
        .gte('published_at', new Date(priorStart).toISOString())
        .not('ig_profile_visits', 'is', null);

      if (error) throw error;

      const daily = Array.from({ length: periodDays }, () => 0);
      let total = 0;
      let prior = 0;

      for (const p of (posts ?? []) as Array<{
        ig_profile_visits: number | null;
        published_at: string | null;
      }>) {
        if (!p.published_at) continue;
        const ts = Date.parse(p.published_at);
        if (!Number.isFinite(ts)) continue;
        const visits = p.ig_profile_visits ?? 0;

        if (ts >= currentStart) {
          total += visits;
          // Bucket into the daily array. Day 0 = oldest, periodDays-1 = today.
          const dayIndex = Math.min(
            periodDays - 1,
            Math.floor((ts - currentStart) / DAY_MS),
          );
          daily[dayIndex]! += visits;
        } else if (ts >= priorStart) {
          prior += visits;
        }
      }

      const deltaPct = prior > 0 ? ((total - prior) / prior) * 100 : null;
      return { total, prior, deltaPct, daily };
    },
  });

  return {
    total: data?.total ?? 0,
    prior: data?.prior ?? 0,
    deltaPct: data?.deltaPct ?? null,
    daily: data?.daily ?? [],
    isLoading: !!userKey && isPending,
    hasError: !!userKey && isError,
  };
}
