// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';
import type { FleetMetricsPlatform } from '@/hooks/useFleetMetrics';

/** 7-row × 24-col engagement grid. Row 0 = Monday, row 6 = Sunday. */
export type HeatmapGrid = number[][];

export interface BestWorstWindow {
  window: string;
  delta: string;
  detail: string;
}

export interface PostingHeatmapState {
  data: HeatmapGrid;
  yourPosts: Set<string>;
  best: BestWorstWindow;
  worst: BestWorstWindow;
  hasRealData: boolean;
  loading: boolean;
}

const MIN_POSTS = 10;
const HOUR_LABELS = (h: number) =>
  h === 0 ? '12am' : h < 12 ? `${h}am` : h === 12 ? '12pm' : `${h - 12}pm`;

function daysToCutoff(days: 7 | 30 | 90): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  d.setHours(0, 0, 0, 0);
  return d.toISOString();
}

function emptyGrid(): HeatmapGrid {
  return Array.from({ length: 7 }, () => new Array<number>(24).fill(0));
}

const EMPTY: Omit<PostingHeatmapState, 'loading'> = {
  data: emptyGrid(),
  yourPosts: new Set(),
  best: { window: '—', delta: '—', detail: 'No data yet' },
  worst: { window: '—', delta: '—', detail: 'No data yet' },
  hasRealData: false,
};

function platformFilter(platform: FleetMetricsPlatform): string | null {
  if (platform === 'threads') return 'threads';
  if (platform === 'instagram') return 'instagram';
  return null;
}

export interface AccountScope {
  accountId: string;
  accountPlatform: 'threads' | 'instagram';
}

export function usePostingHeatmap(
  platform: FleetMetricsPlatform,
  timeframeDays: 7 | 30 | 90,
  accountScope?: AccountScope | null,
): PostingHeatmapState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending } = useQuery({
    queryKey: ['postingHeatmap', userKey, platform, timeframeDays, accountScope?.accountId ?? null],
    enabled: !!userKey,
    // Historical heatmap; data within the timeframe is stable for the day.
    staleTime: 5 * 60_000,
    gcTime: 15 * 60_000,
    queryFn: async () => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return EMPTY;

      const since = daysToCutoff(timeframeDays);
      const pf = platformFilter(platform);

      let query = supabase
        .from('posts')
        .select('platform, published_at, views_count, ig_reach, likes_count, replies_count, reposts_count, quotes_count, ig_saved, ig_shares, ig_comment_count')
        .eq('user_id', user.id)
        .eq('status', 'published')
        .gte('published_at', since)
        .not('published_at', 'is', null);

      if (pf) query = query.eq('platform', pf);

      if (accountScope?.accountId) {
        const col = accountScope.accountPlatform === 'instagram' ? 'instagram_account_id' : 'account_id';
        query = query.eq(col, accountScope.accountId);
      }

      const { data: posts, error } = await query;
      if (error) throw error;
      if (!posts || posts.length < MIN_POSTS) return EMPTY;

      type PostRow = {
        platform: string | null;
        published_at: string | null;
        views_count: number | null;
        ig_reach: number | null;
        likes_count: number | null;
        replies_count: number | null;
        reposts_count: number | null;
        quotes_count: number | null;
        ig_saved: number | null;
        ig_shares: number | null;
        ig_comment_count: number | null;
      };

      // Accumulate total engagement and post count per slot.
      const slotEng = Array.from({ length: 7 }, () => new Array<number>(24).fill(0));
      const slotCount = Array.from({ length: 7 }, () => new Array<number>(24).fill(0));
      const yourPostsSet = new Set<string>();

      for (const p of posts as PostRow[]) {
        if (!p.published_at) continue;
        const d = new Date(p.published_at);
        const dayOfWeek = (d.getDay() + 6) % 7; // Mon=0 … Sun=6
        const hour = d.getHours();

        const reach =
          p.platform === 'instagram'
            ? (p.ig_reach ?? p.views_count ?? 0)
            : (p.views_count ?? 0);
        const eng =
          (p.likes_count ?? 0) +
          (p.replies_count ?? 0) +
          (p.reposts_count ?? 0) +
          (p.quotes_count ?? 0) +
          (p.ig_saved ?? 0) +
          (p.ig_shares ?? 0) +
          (p.ig_comment_count ?? 0);
        const rate = reach > 0 ? (eng / reach) * 100 : 0;

        slotEng[dayOfWeek]![hour]! += rate;
        slotCount[dayOfWeek]![hour]!++;
        yourPostsSet.add(`${dayOfWeek}-${hour}`);
      }

      // Compute average per slot; find max for normalization.
      const rawGrid: number[][] = slotEng.map((row, d) =>
        row.map((total, h) =>
          slotCount[d]![h]! > 0 ? total / slotCount[d]![h]! : 0,
        ),
      );

      const flatValues = rawGrid.flat().filter((v) => v > 0);
      if (flatValues.length === 0) return EMPTY;

      const maxVal = Math.max(...flatValues);
      const data: HeatmapGrid = rawGrid.map((row) =>
        row.map((v) => Math.round((v / maxVal) * 100)),
      );

      // Best and worst occupied slots.
      const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
      let bestD = 0, bestH = 0, bestV = -1;
      let worstD = 0, worstH = 0, worstV = Infinity;

      for (let d = 0; d < 7; d++) {
        for (let h = 0; h < 24; h++) {
          if (slotCount[d]![h] === 0) continue;
          const v = data[d]![h]!;
          if (v > bestV) { bestV = v; bestD = d; bestH = h; }
          if (v < worstV) { worstV = v; worstD = d; worstH = h; }
        }
      }

      const avgAll = flatValues.reduce((s, v) => s + v, 0) / flatValues.length;

      const best: BestWorstWindow = {
        window: `${days[bestD]} ${HOUR_LABELS(bestH)}–${HOUR_LABELS((bestH + 2) % 24)}`,
        delta: `+${Math.round(((rawGrid[bestD]![bestH]! / (avgAll || 1)) - 1) * 100)}% vs avg`,
        detail: `${slotCount[bestD]![bestH]} post${slotCount[bestD]![bestH] === 1 ? '' : 's'} · highest avg engagement`,
      };

      const worst: BestWorstWindow = {
        window: `${days[worstD]} ${HOUR_LABELS(worstH)}–${HOUR_LABELS((worstH + 2) % 24)}`,
        delta: `${Math.round(((rawGrid[worstD]![worstH]! / (avgAll || 1)) - 1) * 100)}% vs avg`,
        detail: `${slotCount[worstD]![worstH]} post${slotCount[worstD]![worstH] === 1 ? '' : 's'} · lowest avg engagement`,
      };

      return { data, yourPosts: yourPostsSet, best, worst, hasRealData: true };
	    },
  });

  return {
    ...(data ?? EMPTY),
    loading: !!userKey && isPending,
  };
}
