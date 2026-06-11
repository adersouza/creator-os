import type { Session } from '@supabase/supabase-js';
import { getStoredSession, supabase } from '@/services/supabase';

let sessionRequest: Promise<Session | null> | null = null;

async function getApiSession(): Promise<Session | null> {
  const stored = getStoredSession();
  if (stored?.access_token) return stored;

  if (!sessionRequest) {
    sessionRequest = supabase.auth
      .getSession()
      .then(({ data }) => data.session ?? null)
      .catch(() => null)
      .finally(() => {
        sessionRequest = null;
      });
  }

  return sessionRequest;
}

export async function getApiAuthHeaders(): Promise<Record<string, string>> {
  const session = await getApiSession();
  return session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {};
}
