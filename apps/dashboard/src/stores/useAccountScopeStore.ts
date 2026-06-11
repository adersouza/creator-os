import { create } from 'zustand';
import { persist } from 'zustand/middleware';

/**
 * Global account scope. When a specific account is selected,
 * Dashboard / Analytics / Calendar / Inbox all filter their data to
 * that account instead of showing aggregate fleet numbers.
 *
 * `null` = "All accounts" (the default; show aggregate fleet data).
 * A scope object = the selected account identity.
 *
 * Persists to localStorage so the operator's context survives a reload.
 */
export interface AccountScopeValue {
  id: string;
  handle: string;
  platform: 'threads' | 'instagram';
}

interface AccountScopeState {
  scopedAccount: AccountScopeValue | null;
  setScope: (scope: AccountScopeValue | null) => void;
  clearScope: () => void;
}

export const useAccountScopeStore = create<AccountScopeState>()(
  persist(
    (set) => ({
      scopedAccount: null,
      setScope: (scope) => set({ scopedAccount: scope }),
      clearScope: () => set({ scopedAccount: null }),
    }),
    {
      name: 'juno33-account-scope',
      version: 2,
      migrate: (persistedState) => {
        const state = persistedState as { scopedAccount?: unknown | undefined } | undefined;
        return {
          scopedAccount:
            state?.scopedAccount &&
            typeof state.scopedAccount === 'object' &&
            typeof (state.scopedAccount as { id?: unknown | undefined }).id === 'string' &&
            typeof (state.scopedAccount as { handle?: unknown | undefined }).handle === 'string' &&
            (((state.scopedAccount as { platform?: unknown | undefined }).platform === 'threads') ||
              ((state.scopedAccount as { platform?: unknown | undefined }).platform === 'instagram'))
              ? (state.scopedAccount as AccountScopeValue)
              : null,
        };
      },
    },
  ),
);
