// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useQuery } from '@tanstack/react-query';
import { useAuthUser } from '@/hooks/useAuthUser';
import { getApiAuthHeaders } from '@/lib/apiAuth';
import { apiUrl } from '@/lib/apiUrl';
import { supabase } from '@/services/supabase';

export interface LinkClickLeader {
  accountId: string;
  username: string | null;
  url: string;
  clicks: number;
  source?: 'url' | 'account-total' | undefined;
}

interface LinkClickResponse {
  leaders: LinkClickLeader[];
  totalClicks: number;
  periodDays: number;
}

interface LinkClickState extends LinkClickResponse {
  isLoading: boolean;
  hasError: boolean;
}

const EMPTY: LinkClickResponse = { leaders: [], totalClicks: 0, periodDays: 14 };

async function fetchLeaders(
  periodDays: number,
  accountId: string | null,
): Promise<LinkClickResponse> {
  const params = new URLSearchParams({ periodDays: String(periodDays) });
  if (accountId) params.set('accountId', accountId);
  const response = await fetch(apiUrl(`/api/analytics?action=link-click-leaders&${params}`), {
    headers: await getApiAuthHeaders(),
  });
  if (!response.ok) throw new Error('Failed to fetch link-click leaders');
  const data = (await response.json()) as LinkClickResponse;
  return {
    leaders: data.leaders ?? [],
    totalClicks: data.totalClicks ?? 0,
    periodDays: data.periodDays ?? periodDays,
  };
}

async function fetchAccountTotalLeaders(
  userId: string,
  periodDays: number,
  accountId: string | null,
): Promise<LinkClickResponse> {
  const since = new Date();
  since.setDate(since.getDate() - periodDays);
  since.setHours(0, 0, 0, 0);
  const sinceDate = since.toISOString().split('T')[0]!;

  let postsQuery = supabase
    .from('posts')
    .select('account_id')
    .eq('user_id', userId)
    .eq('platform', 'threads')
    .eq('status', 'published')
    .not('account_id', 'is', null)
    .gte('published_at', since.toISOString());
  if (accountId) postsQuery = postsQuery.eq('account_id', accountId);

  const { data: postAccounts, error: postsError } = await postsQuery;
  if (postsError) throw postsError;

  const accountIds = Array.from(
    new Set(
      ((postAccounts ?? []) as Array<{ account_id: string | null }>)
        .map((row) => row.account_id)
        .filter((id): id is string => !!id),
    ),
  );
  if (accountIds.length === 0) return { ...EMPTY, periodDays };

  const [analyticsRes, accountsRes] = await Promise.all([
    supabase
      .from('account_analytics')
      .select('account_id, total_clicks')
      .in('account_id', accountIds)
      .gt('total_clicks', 0)
      .gte('date', sinceDate),
    supabase.from('accounts').select('id, username').in('id', accountIds),
  ]);
  if (analyticsRes.error) throw analyticsRes.error;
  if (accountsRes.error) throw accountsRes.error;

  const usernameById = new Map<string, string | null>();
  for (const account of (accountsRes.data ?? []) as Array<{ id: string; username: string | null }>) {
    usernameById.set(account.id, account.username);
  }

  const clicksByAccount = new Map<string, number>();
  let totalClicks = 0;
  for (const row of (analyticsRes.data ?? []) as Array<{
    account_id: string;
    total_clicks: number | null;
  }>) {
    const clicks = row.total_clicks || 0;
    clicksByAccount.set(row.account_id, (clicksByAccount.get(row.account_id) || 0) + clicks);
    totalClicks += clicks;
  }

  const leaders = Array.from(clicksByAccount.entries())
    .map(([id, clicks]) => ({
      accountId: id,
      username: usernameById.get(id) ?? null,
      url: 'Threads aggregate',
      clicks,
      source: 'account-total' as const,
    }))
    .sort((a, b) => b.clicks - a.clicks)
    .slice(0, 8);

  return { leaders, totalClicks, periodDays };
}

/**
 * Top outbound URLs by click volume, reading threads_link_click_breakdown.
 * Threads-only — IG clicks live in account_analytics.ig_website_clicks
 * (no per-URL breakdown from Meta).
 */
export function useLinkClickLeaders(
  periodDays: number = 14,
  accountId: string | null = null,
): LinkClickState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending, isError } = useQuery<LinkClickResponse>({
    queryKey: ['linkClickLeaders', userKey, periodDays, accountId],
    enabled: !!userKey,
    staleTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
    queryFn: async () => {
      const accountTotals = await fetchAccountTotalLeaders(userKey as string, periodDays, accountId);
      const urlBreakdown = await fetchLeaders(periodDays, accountId).catch(() => EMPTY);
      return urlBreakdown.leaders.length > 0 ? urlBreakdown : accountTotals;
    },
  });

  return {
    ...(data ?? EMPTY),
    isLoading: !!userKey && isPending,
    hasError: !!userKey && isError,
  };
}
