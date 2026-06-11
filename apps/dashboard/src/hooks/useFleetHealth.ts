import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';
import { queryKeys } from '@/lib/queryKeys';

export interface FleetGroup {
  id: string;
  name: string;
  color: string;
  count: number;
}

interface FleetHealthState {
  healthy: number;
  warn: number;
  crit: number;
  total: number;
  groups: FleetGroup[];
  isLoading: boolean;
  hasError: boolean;
}

const EMPTY: Omit<FleetHealthState, 'isLoading' | 'hasError'> = {
  healthy: 0, warn: 0, crit: 0, total: 0, groups: [],
};

interface FleetHealthRpc {
  healthy: number;
  warn: number;
  crit: number;
  total: number;
  groups: FleetGroup[];
}

/**
 * Fleet health breakdown via `get_fleet_health` RPC. Classification
 * (healthy/warn/crit based on token + sync recency) + per-group counts
 * all computed server-side. 3 queries + client-side rollup → 1 RPC.
 */
export function useFleetHealth(): FleetHealthState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending, isError } = useQuery({
    queryKey: queryKeys.fleet.health(userKey),
    enabled: !!userKey,
    // Fleet health is an aggregate that updates only as the sync orchestrator
    // runs (every 15 min). 2 min staleTime gives the UI a fresh feel while
    // collapsing dashboard remounts onto a single fetch.
    staleTime: 2 * 60_000,
    gcTime: 10 * 60_000,
    queryFn: async (): Promise<Omit<FleetHealthState, 'isLoading' | 'hasError'>> => {
      const { data, error } = await supabase.rpc('get_fleet_health');
      if (error) throw error;
      if (!data) return EMPTY;
      const r = data as FleetHealthRpc;
      return {
        healthy: r.healthy ?? 0,
        warn: r.warn ?? 0,
        crit: r.crit ?? 0,
        total: r.total ?? 0,
        groups: r.groups ?? [],
      };
    },
  });

  return {
    ...(data ?? EMPTY),
    isLoading: !!userKey && isPending,
    hasError: !!userKey && isError,
  };
}
