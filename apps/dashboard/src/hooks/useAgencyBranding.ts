/**
 * useAgencyBranding — fetches agency branding for white-label PDF exports.
 */

import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/services/supabase';
import { queryClient } from '@/lib/queryClient';
import { useAuthUser } from '@/hooks/useAuthUser';

import { apiUrl } from '@/lib/apiUrl';

export interface AgencyBranding {
  agency_name: string | null;
  agency_logo_url: string | null;
  brand_color: string;
}

const QUERY_KEY_PREFIX = ['agencyBranding'] as const;

/** Clear cached branding on sign-out to prevent stale data across user sessions.
 * Prefix match so every user's agency-branding entry is removed regardless of id. */
export function resetAgencyBrandingCache() {
  queryClient.removeQueries({ queryKey: QUERY_KEY_PREFIX });
}

/** Clear cached branding (call after saving new branding). */
export function invalidateBrandingCache() {
  queryClient.invalidateQueries({ queryKey: QUERY_KEY_PREFIX });
}

export function useAgencyBranding() {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending } = useQuery({
    queryKey: [...QUERY_KEY_PREFIX, userKey],
    enabled: !!userKey,
    staleTime: 10 * 60_000,
    queryFn: async (): Promise<AgencyBranding | null> => {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return null;
      const res = await fetch(apiUrl('/api/agency-branding'), {
        headers: { Authorization: `Bearer ${session.access_token}` },
      });
      const json = await res.json();
      return json.data?.branding || null;
    },
  });

  return { branding: data ?? null, loading: isPending };
}
