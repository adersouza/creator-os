import { useQuery } from '@tanstack/react-query';
import { useAuthUser } from '@/hooks/useAuthUser';
import { queryKeys } from '@/lib/queryKeys';
import { instagramService, type InstagramPublishingQuota } from '@/services/instagramService';
import { supabase } from '@/services/supabase';

export interface InstagramAccountPublishingLimit {
  loginType: string | null;
  quota?: InstagramPublishingQuota | undefined;
  error?: string | undefined;
}

interface State {
  byAccountId: Record<string, InstagramAccountPublishingLimit>;
  isLoading: boolean;
  hasError: boolean;
}

const EMPTY: Record<string, InstagramAccountPublishingLimit> = {};

export function useInstagramPublishingLimits(): State {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending, isError } = useQuery({
    queryKey: queryKeys.system.instagramPublishingLimits(userKey),
    enabled: !!userKey,
    staleTime: 60_000,
    refetchOnWindowFocus: true,
    queryFn: async (): Promise<Record<string, InstagramAccountPublishingLimit>> => {
      if (!userKey) return EMPTY;
      const { data: accounts, error } = await supabase
        .from('instagram_accounts')
        .select('id, login_type')
        .eq('user_id', userKey)
        .eq('is_active', true);
      if (error) throw error;

      const rows = (accounts ?? []) as Array<{ id: string; login_type: string | null }>;
      const result: Record<string, InstagramAccountPublishingLimit> = {};
      for (const row of rows) {
        result[row.id] = { loginType: row.login_type ?? 'instagram' };
      }

      const facebookRows = rows.filter((row) => row.login_type === 'facebook');
      await Promise.all(
        facebookRows.map(async (row) => {
          try {
            const response = await instagramService.getPublishingLimit(row.id);
            result[row.id] = {
              loginType: 'facebook',
              quota: response?.quota,
            };
          } catch (error) {
            result[row.id] = {
              loginType: 'facebook',
              error: error instanceof Error ? error.message : 'Publishing quota unavailable',
            };
          }
        }),
      );

      return result;
    },
  });

  return {
    byAccountId: data ?? EMPTY,
    isLoading: !!userKey && isPending,
    hasError: !!userKey && isError,
  };
}
