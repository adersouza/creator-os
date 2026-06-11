import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/services/supabase';

interface Args {
  accountId: string | null;
  platform: 'threads' | 'instagram';
}

interface State {
  daysLeft: number | null;
  isLoading: boolean;
}

/**
 * Days until token expiry for a single account. Used by the per-account
 * Scorecard donut. Returns `null` when the column is null (long-lived
 * tokens that don't expire) or the account isn't found.
 */
export function useAccountTokenDays({ accountId, platform }: Args): State {
  const table = platform === 'threads' ? 'accounts' : 'instagram_accounts';
  const { data, isPending } = useQuery({
    queryKey: ['accountTokenDays', table, accountId],
    enabled: !!accountId,
    staleTime: 5 * 60 * 1000,
    queryFn: async () => {
      if (!accountId) return null;
      const { data, error } = await supabase
        .from(table)
        .select('token_expires_at')
        .eq('id', accountId)
        .maybeSingle();
      if (error) throw error;
      const expiresAt = (data as { token_expires_at: string | null } | null)?.token_expires_at;
      if (!expiresAt) return null;
      const ms = new Date(expiresAt).getTime() - Date.now();
      return Math.max(0, Math.round(ms / (1000 * 60 * 60 * 24)));
    },
  });
  return { daysLeft: data ?? null, isLoading: isPending };
}
