import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';
import {
  eqsForSignals,
  fillDateRange,
  signalsFor,
  toDateKey,
  type EqsPostRow,
  type PostSignals,
} from '@/lib/eqs';
import type { FleetMetricsPoint } from '@/hooks/useFleetMetrics';

interface ScopedEqsAccountScope {
  accountId: string;
  accountPlatform: 'threads' | 'instagram';
}

type PostRow = EqsPostRow & { published_at: string | null };

export interface ScopedEqsTrendState {
  series: FleetMetricsPoint[];
  previousPoints: number[];
  eqsDelta: number | null;
  loading: boolean;
}

const EMPTY: Omit<ScopedEqsTrendState, 'loading'> = {
  series: [],
  previousPoints: [],
  eqsDelta: null,
};

interface Enriched {
  row: PostRow;
  signal: PostSignals;
}

function buildSeries(rows: Enriched[], start: Date, end: Date): FleetMetricsPoint[] {
  const byDay = new Map<string, PostSignals[]>();
  for (const { row, signal } of rows) {
    if (!row.published_at) continue;
    const key = toDateKey(row.published_at);
    let bucket = byDay.get(key);
    if (!bucket) {
      bucket = [];
      byDay.set(key, bucket);
    }
    bucket.push(signal);
  }
  return fillDateRange(start, end).map((date) => {
    const bucket = byDay.get(date) ?? [];
    return {
      date,
      eqs: eqsForSignals(bucket),
      reach: bucket.reduce((sum, signal) => sum + signal.reach, 0),
    };
  });
}

export function useScopedEqsTrend(
  accountScope: ScopedEqsAccountScope | null | undefined,
  timeframeDays: number,
): ScopedEqsTrendState {
  const authUser = useAuthUser();
  const userKey = authUser?.id ?? null;

  const { data, isPending } = useQuery({
    queryKey: [
      'scopedEqsTrend',
      userKey,
      accountScope?.accountId ?? null,
      accountScope?.accountPlatform ?? null,
      timeframeDays,
    ],
    enabled: !!userKey && !!accountScope?.accountId,
    staleTime: 10 * 60_000,
    queryFn: async () => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user || !accountScope?.accountId) return EMPTY;

      const now = new Date();
      const windowStart = new Date(now.getTime() - timeframeDays * 24 * 60 * 60 * 1000);
      const priorStart = new Date(now.getTime() - 2 * timeframeDays * 24 * 60 * 60 * 1000);
      const windowStartIso = windowStart.toISOString();

      let query = supabase
        .from('posts')
        .select(
          'platform, published_at, likes_count, shares_count, replies_count, views_count, ig_saved, ig_shares, ig_comment_count, ig_reach',
        )
        .eq('user_id', user.id)
        .eq('status', 'published')
        .gte('published_at', priorStart.toISOString())
        .lte('published_at', now.toISOString());

      query = accountScope.accountPlatform === 'instagram'
        ? query.eq('instagram_account_id', accountScope.accountId)
        : query.eq('account_id', accountScope.accountId);

      const { data: posts, error } = await query;
      if (error) throw error;

      const current: Enriched[] = [];
      const prior: Enriched[] = [];
      for (const post of (posts ?? []) as PostRow[]) {
        if (!post.published_at) continue;
        const signal = signalsFor(post);
        if (post.published_at >= windowStartIso) current.push({ row: post, signal });
        else prior.push({ row: post, signal });
      }

      const currentSignals = current.map((e) => e.signal);
      const priorSignals = prior.map((e) => e.signal);
      const currentEqs = eqsForSignals(currentSignals);
      const priorEqs = eqsForSignals(priorSignals);
      const priorReach = priorSignals.reduce((sum, signal) => sum + signal.reach, 0);
      const eqsDelta =
        prior.length === 0 || priorReach <= 0
          ? null
          : Math.round((currentEqs - priorEqs) * 10) / 10;

      const priorEnd = new Date(windowStart.getTime() - 24 * 60 * 60 * 1000);
      const series = buildSeries(current, windowStart, now);
      const previousPoints = buildSeries(prior, priorStart, priorEnd).map((point) => point.eqs);

      return {
        series,
        previousPoints,
        eqsDelta,
      };
    },
  });

  return {
    ...(data ?? EMPTY),
    loading: !!accountScope?.accountId && !!userKey && isPending,
  };
}
