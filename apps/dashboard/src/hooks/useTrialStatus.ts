import { useQuery } from '@tanstack/react-query';
import { z } from 'zod';
import { apiFetch } from '@/lib/apiFetch';
import { useAuthUser } from '@/hooks/useAuthUser';
import { queryKeys } from '@/lib/queryKeys';

// Runtime-validated response shape — if the backend drifts, we fail
// fast at the fetch boundary instead of silently rehydrating garbage.
const TrialStatusSchema = z.object({
  daysRemaining: z.number().optional(),
  tier: z.string().optional(),
  plan: z.string().optional(),
  active: z.boolean().optional(),
}).passthrough();

export function useTrialStatus() {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data } = useQuery({
    queryKey: queryKeys.system.trialStatus(userKey),
    enabled: !!userKey,
    staleTime: 5 * 60_000,
    gcTime: 30 * 60_000,
    queryFn: async (): Promise<number> => {
      const res = await apiFetch(
        '/api/subscription?action=check-trial',
        TrialStatusSchema,
        { method: 'POST', json: {} },
      );
      return typeof res.daysRemaining === 'number' && res.daysRemaining > 0 ? res.daysRemaining : 0;
    },
  });

  const daysRemaining = data ?? 0;
  return { daysRemaining, isTrialing: daysRemaining > 0 };
}
