import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';
import {
  summarizeFleetRetention,
  type FleetRetentionSummary,
} from '@/lib/reelRetention';
import { queryKeys } from '@/lib/queryKeys';

/**
 * Reel Retention Flash — fleet-wide watch-time-quality signal for IG Reels.
 *
 * Pulls published IG Reels in the selected window that have any
 * retention metric set by the backend analyticsSync (ig_reels_avg_watch_time
 * and ig_skip_rate) and rolls them up via pure helpers in lib/reelRetention.
 *
 * hasRealData: true when ≥ MIN_SAMPLE Reels have scorable data. Widget
 * shows a Demo badge below that threshold rather than confidently-wrong
 * fleet averages from a 2-Reel sample.
 */

interface State {
  summary: FleetRetentionSummary;
  loading: boolean;
  hasRealData: boolean;
}

const MIN_SAMPLE = 10;

function timeframeDaysToCutoff(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  d.setHours(0, 0, 0, 0);
  return d.toISOString();
}

const EMPTY_SUMMARY: FleetRetentionSummary = {
  sampledReels: 0,
  avgScore: 0,
  byBucket: { excellent: 0, strong: 0, weak: 0, sub3: 0 },
  sub3Rate: 0,
};

export function useReelRetention(
  timeframeDays: number,
  instagramAccountId?: string | null,
): State {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending } = useQuery({
    queryKey: queryKeys.analytics.reelRetention(
      userKey,
      timeframeDays,
      instagramAccountId,
    ),
    enabled: !!userKey,
    queryFn: async () => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return { summary: EMPTY_SUMMARY, hasRealData: false };

      const since = timeframeDaysToCutoff(timeframeDays);
      let query = supabase
        .from('posts')
        .select(
          'ig_reels_avg_watch_time, ig_skip_rate, views_count',
        )
        .eq('user_id', user.id)
        .eq('platform', 'instagram')
        .eq('status', 'published')
        .gte('published_at', since);

      if (instagramAccountId) {
        query = query.eq('instagram_account_id', instagramAccountId);
      }

      const { data, error } = await query;

      if (error) throw error;

      const rows = (data ?? []) as Array<{
        ig_reels_avg_watch_time: number | null;
        ig_skip_rate: number | null;
        views_count: number | null;
      }>;

      const summary = summarizeFleetRetention(
        rows.map((r) => ({
          avgWatchMs: r.ig_reels_avg_watch_time,
          skipRate: r.ig_skip_rate,
          views: r.views_count,
        })),
      );

      return {
        summary,
        hasRealData: summary.sampledReels >= MIN_SAMPLE,
      };
    },
  });

  return {
    summary: data?.summary ?? EMPTY_SUMMARY,
    hasRealData: data?.hasRealData ?? false,
    loading: !!userKey && isPending,
  };
}
