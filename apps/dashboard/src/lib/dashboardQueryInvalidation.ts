import type { QueryClient } from '@tanstack/react-query';
import { resetFleetAccountsCache } from '@/hooks/useFleetAccounts';
import { resetFleetKpiDataCache } from '@/hooks/useFleetKpiData';
import { resetFleetMetricsCache } from '@/hooks/useFleetMetrics';
import { resetTopPostsCache } from '@/hooks/useTopPosts';
import { bumpDashboardRefreshRevision } from '@/lib/dashboardRefreshSignal';
import { DASHBOARD_QUERY_PREFIXES } from '@/lib/dashboardQueryRoots';

export function invalidateDashboardQueries(queryClient: QueryClient): Promise<void> {
  resetFleetAccountsCache();
  resetFleetKpiDataCache();
  resetFleetMetricsCache();
  resetTopPostsCache();
  bumpDashboardRefreshRevision();

  return Promise.all(
    DASHBOARD_QUERY_PREFIXES.map((prefix) =>
      queryClient.invalidateQueries({ queryKey: [prefix] }),
    ),
  ).then(() => undefined);
}
