import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';
import { queryKeys } from '@/lib/queryKeys';

export interface SystemStatusState {
  queueDepthDays: number | null;
  publishSuccessPct: number | null;
  pendingApprovals: number;
  oldestApprovalHours: number | null;
  isLoading: boolean;
  hasError: boolean;
}

const EMPTY: Omit<SystemStatusState, 'isLoading' | 'hasError'> = {
  queueDepthDays: null,
  publishSuccessPct: null,
  pendingApprovals: 0,
  oldestApprovalHours: null,
};

interface SystemStatusRpc {
  queueDepthDays: number | null;
  publishSuccessPct: number | null;
  pendingApprovals: number;
  oldestApprovalHours: number | null;
}

/**
 * Cheap snapshot of operator system health via `get_system_status` RPC.
 * 6 Supabase round-trips collapsed into 1 — see
 * supabase/migrations/20260418040000_juno33_dashboard_rpcs.sql
 */
export function useSystemStatus(): SystemStatusState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending, isError } = useQuery({
    queryKey: queryKeys.system.status(userKey),
    enabled: !!userKey,
    queryFn: async (): Promise<Omit<SystemStatusState, 'isLoading' | 'hasError'>> => {
      const { data, error } = await supabase.rpc('get_system_status');
      if (error) throw error;
      if (!data) return EMPTY;
      const r = data as SystemStatusRpc;
      return {
        queueDepthDays: r.queueDepthDays,
        publishSuccessPct: r.publishSuccessPct,
        pendingApprovals: r.pendingApprovals ?? 0,
        oldestApprovalHours: r.oldestApprovalHours,
      };
    },
  });

  return {
    ...(data ?? EMPTY),
    isLoading: !!userKey && isPending,
    hasError: !!userKey && isError,
  };
}
