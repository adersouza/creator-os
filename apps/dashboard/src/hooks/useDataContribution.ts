/**
 * useDataContribution — reads + writes the caller's anonymized cohort-sharing
 * preference.
 *
 * Read: GET /api/user?action=data-contribution.
 * Write: POST /api/user?action=data-contribution with { opted_in, niche }.
 *
 * The CohortChip unlock logic and the Settings opt-in card both depend on
 * this hook. Keep it small — if cohort features grow, compose around it
 * rather than swelling it.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuthUser } from '@/hooks/useAuthUser';
import { apiUrl } from '@/lib/apiUrl';
import type { CanonicalNiche } from '@/lib/cohorts';
import { supabase } from '@/services/supabase';

export interface DataContributionState {
  optedIn: boolean;
  niche: CanonicalNiche | null;
}

const QUERY_KEY_PREFIX = ['dataContribution'] as const;

export function useDataContribution() {
  const authUser = useAuthUser();
  const userKey = authUser?.id ?? null;
  const qc = useQueryClient();

  const { data, isPending } = useQuery({
    queryKey: [...QUERY_KEY_PREFIX, userKey],
    enabled: !!userKey,
    staleTime: 60_000,
    queryFn: async (): Promise<DataContributionState> => {
      if (!userKey) return { optedIn: false, niche: null };

      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return { optedIn: false, niche: null };

      const res = await fetch(apiUrl('/api/user?action=data-contribution'), {
        headers: { Authorization: `Bearer ${session.access_token}` },
      });
      if (!res.ok) return { optedIn: false, niche: null };
      const body = (await res.json().catch(() => ({}))) as {
        data?: { opted_in?: boolean | undefined; niche?: CanonicalNiche | null | undefined } | undefined;
      };

      return {
        optedIn: body.data?.opted_in === true,
        niche: body.data?.niche ?? null,
      };
    },
  });

  const mutation = useMutation({
    mutationFn: async (next: { opted_in: boolean; niche?: CanonicalNiche | null | undefined }) => {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) throw new Error('Not authenticated');

      const res = await fetch(apiUrl('/api/user?action=data-contribution'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${session.access_token}`,
        },
        body: JSON.stringify(next),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body?.error ?? `Request failed (${res.status})`);
      }
      return (await res.json()) as { data: { opted_in: boolean; niche: CanonicalNiche | null } };
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QUERY_KEY_PREFIX });
    },
  });

  return {
    optedIn: data?.optedIn ?? false,
    niche: data?.niche ?? null,
    loading: isPending,
    saving: mutation.isPending,
    error: mutation.error as Error | null,
    setContribution: (opted_in: boolean, niche: CanonicalNiche | null) =>
      mutation.mutateAsync({ opted_in, niche }),
  };
}
