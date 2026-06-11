import { useCallback } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { supabase } from '@/services/supabase';
import { queryClient } from '@/lib/queryClient';
import { queryKeys } from '@/lib/queryKeys';
import { useAuthUser } from '@/hooks/useAuthUser';
import { resetFleetAccountsCache } from '@/hooks/useFleetAccounts';
import { resetFleetMetricsCache } from '@/hooks/useFleetMetrics';
import { resetTopPostsCache } from '@/hooks/useTopPosts';

export interface AccountGroup {
  id: string;
  name: string;
  color: string;
  accountIds: string[];
}

interface State {
  groups: AccountGroup[];
  isLoading: boolean;
  createGroup: (input: { name: string; color: string; accountIds: string[] }) => Promise<AccountGroup | null>;
  updateGroup: (input: { id: string; name: string; color: string }) => Promise<AccountGroup | null>;
  deleteGroup: (id: string) => Promise<void>;
}

const UNASSIGNED_COLOR = '#6B6B70';

/**
 * Operator's account groups. Onboarding (Welcome step 2) seeds them;
 * Composer's "+ Create group" extends the list at publish-time.
 */
export function useAccountGroups(): State {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending } = useQuery({
    queryKey: queryKeys.accounts.groups(userKey),
    enabled: !!userKey,
    // Groups change rarely; mutations explicitly invalidate this key, so
    // a long stale window is safe and prevents the duplicate fetches that
    // happen when several dashboard and analytics panels mount this hook on
    // the same route.
    staleTime: 5 * 60_000,
    gcTime: 15 * 60_000,
    queryFn: async (): Promise<AccountGroup[]> => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return [];

      const { data, error } = await supabase
        .from('account_groups')
        .select('id, name, color, account_ids')
        .eq('user_id', user.id)
        .order('name', { ascending: true });

      if (error) throw error;

      return (data ?? []).map((g) => ({
        id: g.id,
        name: g.name,
        color: g.color || UNASSIGNED_COLOR,
        accountIds: g.account_ids ?? [],
      }));
    },
  });

  const createMutation = useMutation({
    mutationFn: async (input: { name: string; color: string; accountIds: string[] }): Promise<AccountGroup | null> => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return null;

      const { data, error } = await supabase
        .from('account_groups')
        .insert({
          user_id: user.id,
          name: input.name,
          color: input.color,
          account_ids: input.accountIds,
        })
        .select('id, name, color, account_ids')
        .single();

      if (error || !data) return null;

      const targetIds = input.accountIds;
      if (targetIds.length > 0) {
        const [threadsRes, instagramRes] = await Promise.all([
          supabase
            .from('accounts')
            .select('id')
            .eq('user_id', user.id)
            .in('id', targetIds),
          supabase
            .from('instagram_accounts')
            .select('id')
            .eq('user_id', user.id)
            .in('id', targetIds),
        ]);

        const threadIds = (threadsRes.data ?? []).map((row) => row.id);
        const instagramIds = (instagramRes.data ?? []).map((row) => row.id);
        const updatedAt = new Date().toISOString();

        const [threadUpdate, instagramUpdate] = await Promise.all([
          threadIds.length > 0
            ? supabase
                .from('accounts')
                .update({ group_id: data.id, updated_at: updatedAt })
                .eq('user_id', user.id)
                .in('id', threadIds)
            : Promise.resolve({ error: null }),
          instagramIds.length > 0
            ? supabase
                .from('instagram_accounts')
                .update({ group_id: data.id, updated_at: updatedAt })
                .eq('user_id', user.id)
                .in('id', instagramIds)
            : Promise.resolve({ error: null }),
        ]);

        if (threadsRes.error || instagramRes.error || threadUpdate.error || instagramUpdate.error) {
          throw threadsRes.error ?? instagramRes.error ?? threadUpdate.error ?? instagramUpdate.error;
        }
      }

      return {
        id: data.id,
        name: data.name,
        color: data.color || UNASSIGNED_COLOR,
        accountIds: data.account_ids ?? [],
      };
    },
    onSuccess: (created) => {
      if (!created) return;
      queryClient.setQueryData<AccountGroup[]>(queryKeys.accounts.groups(userKey), (prev) => {
        const next = [...(prev ?? []), created];
        return next.sort((a, b) => a.name.localeCompare(b.name));
      });
      resetFleetAccountsCache();
      resetFleetMetricsCache();
      resetTopPostsCache();
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.accounts.connectedAll }),
        queryClient.invalidateQueries({ queryKey: queryKeys.fleet.healthAll }),
        queryClient.invalidateQueries({ queryKey: queryKeys.posts.nextUpAll }),
        queryClient.invalidateQueries({ queryKey: queryKeys.posts.needsAttentionAll }),
      ]);
    },
  });

  const updateMutation = useMutation({
    mutationFn: async (input: { id: string; name: string; color: string }): Promise<AccountGroup | null> => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return null;

      const { data, error } = await supabase
        .from('account_groups')
        .update({
          name: input.name,
          color: input.color,
          updated_at: new Date().toISOString(),
        })
        .eq('id', input.id)
        .eq('user_id', user.id)
        .select('id, name, color, account_ids')
        .single();

      if (error || !data) return null;

      return {
        id: data.id,
        name: data.name,
        color: data.color || UNASSIGNED_COLOR,
        accountIds: data.account_ids ?? [],
      };
    },
    onSuccess: (updated) => {
      if (!updated) return;
      queryClient.setQueryData<AccountGroup[]>(queryKeys.accounts.groups(userKey), (prev) => (
        (prev ?? [])
          .map((group) => (group.id === updated.id ? updated : group))
          .sort((a, b) => a.name.localeCompare(b.name))
      ));
      resetFleetAccountsCache();
      resetFleetMetricsCache();
      resetTopPostsCache();
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.accounts.connectedAll }),
        queryClient.invalidateQueries({ queryKey: queryKeys.fleet.healthAll }),
        queryClient.invalidateQueries({ queryKey: queryKeys.posts.nextUpAll }),
        queryClient.invalidateQueries({ queryKey: queryKeys.posts.needsAttentionAll }),
      ]);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: string): Promise<void> => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) throw new Error('Not authenticated');

      const updatedAt = new Date().toISOString();
      const [threadsRes, instagramRes] = await Promise.all([
        supabase
          .from('accounts')
          .update({ group_id: null, updated_at: updatedAt })
          .eq('user_id', user.id)
          .eq('group_id', id),
        supabase
          .from('instagram_accounts')
          .update({ group_id: null, updated_at: updatedAt })
          .eq('user_id', user.id)
          .eq('group_id', id),
      ]);

      if (threadsRes.error) throw threadsRes.error;
      if (instagramRes.error) throw instagramRes.error;

      const { error } = await supabase
        .from('account_groups')
        .delete()
        .eq('id', id)
        .eq('user_id', user.id);
      if (error) throw error;
    },
    onSuccess: (_result, id) => {
      queryClient.setQueryData<AccountGroup[]>(queryKeys.accounts.groups(userKey), (prev) => (
        (prev ?? []).filter((group) => group.id !== id)
      ));
      resetFleetAccountsCache();
      resetFleetMetricsCache();
      resetTopPostsCache();
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.accounts.connectedAll }),
        queryClient.invalidateQueries({ queryKey: queryKeys.fleet.healthAll }),
        queryClient.invalidateQueries({ queryKey: queryKeys.posts.nextUpAll }),
        queryClient.invalidateQueries({ queryKey: queryKeys.posts.needsAttentionAll }),
      ]);
    },
  });

  const createGroup = useCallback<State['createGroup']>(
    (input) => createMutation.mutateAsync(input),
    [createMutation],
  );
  const updateGroup = useCallback<State['updateGroup']>(
    (input) => updateMutation.mutateAsync(input),
    [updateMutation],
  );
  const deleteGroup = useCallback<State['deleteGroup']>(
    (id) => deleteMutation.mutateAsync(id),
    [deleteMutation],
  );

  return {
    groups: data ?? [],
    isLoading: !!userKey && isPending,
    createGroup,
    updateGroup,
    deleteGroup,
  };
}
