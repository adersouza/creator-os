import { useEffect, useMemo, useState } from 'react';
import { supabase } from '@/services/supabase';
import type { FleetAccount } from '@/hooks/useFleetAccounts';
import { chunkAccountIds } from '@/lib/accountIdBatching';

export interface AccountCapabilityError {
  id: string;
  account_id: string;
  capability: string;
  error_code: string;
  message: string;
  blocked_until: string | null;
  last_seen_at: string;
  resolved_at: string | null;
}

interface AccountTokenHealthState {
  capability_errors: AccountCapabilityError[];
  capabilityErrorsByAccount: Map<string, AccountCapabilityError[]>;
}

export function useAccountTokenHealth(accounts: FleetAccount[]): AccountTokenHealthState {
  const [capabilityErrors, setCapabilityErrors] = useState<AccountCapabilityError[]>([]);

  useEffect(() => {
    let cancelled = false;
    const threadIds = accounts.filter((account) => account.platform === 'threads').map((account) => account.id);
    if (threadIds.length === 0) {
      setCapabilityErrors([]);
      return;
    }

    (async () => {
      const results = await Promise.all(
        chunkAccountIds(threadIds).map((ids) =>
          supabase
            .from('account_capability_errors')
            .select('id, account_id, capability, error_code, message, blocked_until, last_seen_at, resolved_at')
            .in('account_id', ids)
            .is('resolved_at', null)
            .order('last_seen_at', { ascending: false }),
        ),
      );
      if (cancelled) return;
      const error = results.find((result) => result.error)?.error;
      setCapabilityErrors(error ? [] : results.flatMap((result) => (result.data ?? []) as AccountCapabilityError[]));
    })();

    return () => {
      cancelled = true;
    };
  }, [accounts]);

  const capabilityErrorsByAccount = useMemo(() => {
    const byAccount = new Map<string, AccountCapabilityError[]>();
    for (const error of capabilityErrors) {
      const list = byAccount.get(error.account_id) ?? [];
      list.push(error);
      byAccount.set(error.account_id, list);
    }
    return byAccount;
  }, [capabilityErrors]);

  return {
    capability_errors: capabilityErrors,
    capabilityErrorsByAccount,
  };
}
