// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useEffect, useState } from 'react';
import type { User } from '@supabase/supabase-js';
import { supabase, supabaseAuth, getStoredUser } from '@/services/supabase';

export interface AuthUserSummary {
  id: string;
  name: string;
  firstName: string;
  email: string;
  avatarUrl: string | null;
  initial: string;
}

// Module-scoped cache of the last hydrated user. Every page remount calls
// useAuthUser() from scratch — without this, the first render always returns
// null while getUser() runs async, which cascades into empty-state flashes in
// the SWR hooks that gate their cache lookups on userKey. Persisting here
// means subsequent mounts get the signed-in identity synchronously. Cleared
// via onAuthStateChange below when the session actually ends.
let cachedUser: AuthUserSummary | null = null;

function toSummary(raw: User | null): AuthUserSummary | null {
  if (!raw) return null;
  const meta = (raw.user_metadata ?? {}) as {
    full_name?: string | undefined;
    name?: string | undefined;
    avatar_url?: string | undefined;
    picture?: string | undefined;
  };
  const rawName = meta.full_name || meta.name || '';
  const email = raw.email ?? '';
  const display = rawName || (email ? email.split('@')[0] : 'Operator');
  const firstName = display!.split(' ')[0] || display;
  const initial = (rawName || email || 'A').trim().charAt(0).toUpperCase() || 'A';
  return {
    id: raw.id,
    name: display!,
    firstName: firstName!,
    email,
    avatarUrl: meta.avatar_url || meta.picture || null,
    initial,
  };
}

/**
 * Live Supabase user reduced to the fields the UI actually reads
 * (name/firstName/email/avatar/initial). Bootstraps with getUser() and
 * stays in sync via onAuthStateChange. Returns null when signed out.
 */
export function useAuthUser(): AuthUserSummary | null {
  const [user, setUser] = useState<AuthUserSummary | null>(
    cachedUser ?? toSummary(getStoredUser()),
  );

  useEffect(() => {
    let cancelled = false;

    const hydrate = (raw: User | null) => {
      if (cancelled) return;
      const next = toSummary(raw);
      cachedUser = next;
      setUser(next);
    };

    supabaseAuth.getUser().then((u) => hydrate(u)).catch(() => hydrate(getStoredUser()));
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      hydrate(session?.user ?? null);
    });

    return () => {
      cancelled = true;
      subscription.unsubscribe();
    };
  }, []);

  return user;
}
