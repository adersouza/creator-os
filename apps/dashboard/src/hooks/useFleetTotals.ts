import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';
import { fetchConnectedAccounts } from '@/hooks/useConnectedAccounts';
import { queryClient } from '@/lib/queryClient';
import { queryKeys } from '@/lib/queryKeys';

interface FleetTotals {
  accounts: number;
  scheduledToday: number;
  isLoading: boolean;
  hasError: boolean;
}

export function useFleetTotals(): FleetTotals {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending, isError } = useQuery({
    queryKey: queryKeys.fleet.totals(userKey),
    enabled: !!userKey,
    queryFn: async () => {
      if (!userKey) return { accounts: 0, scheduledToday: 0 };

      const todayStart = new Date();
      todayStart.setHours(0, 0, 0, 0);
      const tomorrowStart = new Date(todayStart);
      tomorrowStart.setDate(tomorrowStart.getDate() + 1);

      const [accounts, scheduledRes] = await Promise.all([
        queryClient.fetchQuery({
          queryKey: queryKeys.accounts.connected(userKey),
          staleTime: 5 * 60_000,
          gcTime: 15 * 60_000,
          queryFn: () => fetchConnectedAccounts(userKey),
        }),
        supabase
          .from('posts')
          .select('id', { count: 'exact' })
          .eq('user_id', userKey)
          .eq('status', 'scheduled')
          .gte('scheduled_for', todayStart.toISOString())
          .lt('scheduled_for', tomorrowStart.toISOString())
          .limit(1),
      ]);

      if (scheduledRes.error) throw scheduledRes.error;

      return {
        accounts: accounts.length,
        scheduledToday: scheduledRes.count ?? 0,
      };
    },
  });

  return {
    accounts: data?.accounts ?? 0,
    scheduledToday: data?.scheduledToday ?? 0,
    isLoading: !!userKey && isPending,
    hasError: !!userKey && isError,
  };
}
