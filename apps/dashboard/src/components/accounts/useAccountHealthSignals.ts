import { useCallback, useEffect, useMemo, useState } from 'react';
import type { FleetAccount } from '@/hooks/useFleetAccounts';
import { useAccountTokenHealth } from '@/hooks/useAccountTokenHealth';
import { supabase } from '@/services/supabase';
import { chunkAccountIds } from '@/lib/accountIdBatching';
import { hasTokenExpiringSignal, type AccountHealthSignal } from './shared';

export function useAccountHealthSignals(accounts: FleetAccount[]) {
  const [signals, setSignals] = useState<AccountHealthSignal[]>([]);
  const [signalsRevision, setSignalsRevision] = useState(0);
  const refreshSignals = useCallback(() => setSignalsRevision((value) => value + 1), []);
  const { capability_errors } = useAccountTokenHealth(accounts);

  useEffect(() => {
    void signalsRevision;
    let cancelled = false;
    const threadIds = accounts.filter((account) => account.platform === 'threads').map((account) => account.id);
    if (threadIds.length === 0) {
      setSignals([]);
      return;
    }
    (async () => {
      const results = await Promise.all(
        chunkAccountIds(threadIds).map((ids) =>
          supabase
            .from('account_health_signals')
            .select('id, account_id, signal_type, severity, metadata, detected_at, resolved_at')
            .in('account_id', ids)
            .order('detected_at', { ascending: false }),
        ),
      );
      if (cancelled) return;
      const error = results.find((result) => result.error)?.error;
      setSignals(error ? [] : results.flatMap((result) => (result.data ?? []) as AccountHealthSignal[]));
    })();
    return () => {
      cancelled = true;
    };
  }, [accounts, signalsRevision]);

  const healthSignalsByAccount = useMemo(() => {
    const byAccount = new Map<string, AccountHealthSignal[]>();
    for (const signal of signals) {
      const list = byAccount.get(signal.account_id) ?? [];
      list.push(signal);
      byAccount.set(signal.account_id, list);
    }
    for (const account of accounts) {
      const existing = byAccount.get(account.id) ?? [];
      const capabilitySignals = capability_errors
        .filter((error) => error.account_id === account.id && !error.resolved_at)
        .map<AccountHealthSignal>((error) => ({
          id: `capability-${error.id}`,
          account_id: error.account_id,
          signal_type: 'capability_error',
          severity: 'warn',
          metadata: {
            capability: error.capability,
            error_code: error.error_code,
            message: error.message,
            blocked_until: error.blocked_until,
          },
          detected_at: error.last_seen_at,
          resolved_at: error.resolved_at,
        }));
      const tokenSoon = account.needsReauth || (account.tokenDaysLeft !== null && account.tokenDaysLeft <= 7);
      if (tokenSoon && !hasTokenExpiringSignal(existing)) {
        byAccount.set(account.id, [
          {
            id: `local-token-${account.id}`,
            account_id: account.id,
            signal_type: 'token_expiring',
            severity:
              account.needsReauth || (account.tokenDaysLeft !== null && account.tokenDaysLeft < 0)
                ? 'critical'
                : 'warn',
            metadata: { source: 'client_token_window' },
            detected_at: account.tokenExpiresAt ?? new Date().toISOString(),
            resolved_at: null,
          },
          ...capabilitySignals,
          ...existing,
        ]);
      } else if (capabilitySignals.length > 0) {
        byAccount.set(account.id, [...capabilitySignals, ...existing]);
      }
    }
    return byAccount;
  }, [accounts, capability_errors, signals]);

  return { healthSignalsByAccount, refreshSignals };
}
