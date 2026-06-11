import { useSyncExternalStore } from 'react';

let revision = 0;
const listeners = new Set<() => void>();

export function bumpDashboardRefreshRevision(): void {
  revision += 1;
  for (const listener of listeners) listener();
}

export function useDashboardRefreshRevision(): number {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => revision,
    () => revision,
  );
}
