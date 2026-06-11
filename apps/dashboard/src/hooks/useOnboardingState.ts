import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/services/supabase';
import { queryClient } from '@/lib/queryClient';
import { readLocalOnboardingComplete } from '@/lib/onboarding';
import { useAuthUser } from '@/hooks/useAuthUser';
import { fetchConnectedAccounts } from '@/hooks/useConnectedAccounts';
import { queryKeys } from '@/lib/queryKeys';

export interface OnboardingState {
  isOnboardingComplete: boolean;
  connectedAccountCount: number;
  hasConnectedAccounts: boolean;
  timezone: string | null;
  postingWindows: string[];
  ready: boolean;
}

const DEFAULT: OnboardingState = {
  isOnboardingComplete: false,
  connectedAccountCount: 0,
  hasConnectedAccounts: false,
  timezone: null,
  postingWindows: [],
  ready: false,
};

export function useOnboardingState(): OnboardingState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isSuccess } = useQuery({
    queryKey: queryKeys.onboarding.state(userKey),
    enabled: !!userKey,
    staleTime: 60_000,
    queryFn: async (): Promise<Omit<OnboardingState, 'ready'>> => {
      // React StrictMode double-invokes this in dev — both passes race for
      // the Supabase auth-token lock. The second call steals it and the first
      // rejects with AbortError. Swallow that so the winning call proceeds.
      let userRes: Awaited<ReturnType<typeof supabase.auth.getUser>>['data'] | null = null;
      try {
        const res = await supabase.auth.getUser();
        userRes = res.data;
      } catch (err) {
        if (err && typeof err === 'object' && 'name' in err && (err as { name: string }).name === 'AbortError') {
          return { ...DEFAULT };
        }
        throw err;
      }
      const user = userRes?.user;
      if (!user) return { ...DEFAULT };

      const meta = (user.user_metadata ?? {}) as {
        onboarding_completed_at?: string | undefined;
        connected_account_count?: number | undefined;
        timezone?: string | undefined;
        posting_windows?: string[] | undefined;
      };

      const metaCount =
        typeof meta.connected_account_count === 'number' ? meta.connected_account_count : 0;
      const connectedAccounts = await queryClient.fetchQuery({
        queryKey: queryKeys.accounts.connected(user.id),
        staleTime: 5 * 60_000,
        gcTime: 15 * 60_000,
        queryFn: () => fetchConnectedAccounts(user.id),
      });
      const liveCount = connectedAccounts.length;
      const count = Math.max(liveCount, metaCount);

      const localFlag = readLocalOnboardingComplete(user.id);
      return {
        isOnboardingComplete: Boolean(meta.onboarding_completed_at) || localFlag,
        connectedAccountCount: count,
        hasConnectedAccounts: liveCount > 0,
        timezone: meta.timezone ?? null,
        postingWindows: Array.isArray(meta.posting_windows) ? meta.posting_windows : [],
      };
    },
  });

  useEffect(() => {
    const { data: sub } = supabase.auth.onAuthStateChange(() => {
      queryClient.invalidateQueries({ queryKey: queryKeys.onboarding.all });
    });
    return () => sub?.subscription.unsubscribe();
  }, []);

  if (!isSuccess) return DEFAULT;
  return { ...(data ?? DEFAULT), ready: true };
}
