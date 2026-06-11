import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';
import { withAnalyticsQueryTimeout } from '@/lib/analyticsQueryTimeout';

export type IGFormatType = 'Reels' | 'Stories' | 'Carousels' | 'Images';

export interface IGFormatStat {
  type: IGFormatType;
  posts: number;
  avgViews: number;
  avgLikes: number;
  avgSaves: number;
  qwe: number;
  retentionPct: number | null;
  sharePct: number;
}

export interface IGFormatBreakdownState {
  formats: IGFormatStat[];
  hasRealData: boolean;
  loading: boolean;
}

const EMPTY: Omit<IGFormatBreakdownState, 'loading'> = {
  formats: [],
  hasRealData: false,
};

const MIN_POSTS = 5;

function daysToCutoff(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  d.setHours(0, 0, 0, 0);
  return d.toISOString();
}

function detectFormat(igMediaType: string | null, isCarousel: boolean | null): IGFormatType {
  const mt = (igMediaType ?? '').toUpperCase();
  if (mt === 'REELS') return 'Reels';
  if (mt === 'STORIES') return 'Stories';
  if (isCarousel || mt === 'CAROUSEL_ALBUM') return 'Carousels';
  return 'Images';
}

export function useIGFormatBreakdown(
  timeframeDays: number,
  accountId: string | null = null,
  accountIds?: string[],
): IGFormatBreakdownState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending } = useQuery({
    queryKey: ['igFormatBreakdown', userKey, timeframeDays, accountId, accountIds?.join(',') ?? null],
    enabled: !!userKey,
    staleTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
    retry: false,
    queryFn: () => withAnalyticsQueryTimeout((async () => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return EMPTY;

      const since = daysToCutoff(timeframeDays);
      let query = supabase
        .from('posts')
        .select('ig_media_type, is_carousel, likes_count, ig_comment_count, ig_saved, views_count, ig_reach, ig_reels_plays, ig_skip_rate')
        .eq('user_id', user.id)
        .eq('platform', 'instagram')
        .eq('status', 'published')
        .gte('published_at', since);
      if (accountId) query = query.eq('instagram_account_id', accountId);
      else if (accountIds && accountIds.length > 0) query = query.in('instagram_account_id', accountIds);

      const { data: posts, error } = await query;

      if (error) throw error;
      if (!posts || posts.length < MIN_POSTS) return EMPTY;

      type PostRow = {
        ig_media_type: string | null;
        is_carousel: boolean | null;
        likes_count: number | null;
        ig_comment_count: number | null;
        ig_saved: number | null;
        views_count: number | null;
        ig_reach: number | null;
        ig_reels_plays: number | null;
        ig_skip_rate: number | null;
      };

      const ORDER: IGFormatType[] = ['Reels', 'Stories', 'Carousels', 'Images'];
      const buckets = Object.fromEntries(
        ORDER.map((t) => [
          t,
          { posts: 0, likes: 0, saves: 0, comments: 0, views: 0, reelPlays: 0, skipRateSum: 0, skipCount: 0 },
        ]),
      ) as Record<
        IGFormatType,
        {
          posts: number;
          likes: number;
          saves: number;
          comments: number;
          views: number;
          reelPlays: number;
          skipRateSum: number;
          skipCount: number;
        }
      >;

      for (const p of posts as PostRow[]) {
        const fmt = detectFormat(p.ig_media_type, p.is_carousel);
        const b = buckets[fmt];
        b.posts++;
        b.likes += p.likes_count ?? 0;
        b.saves += p.ig_saved ?? 0;
        b.comments += p.ig_comment_count ?? 0;
        b.views += p.ig_reach ?? p.views_count ?? 0;
        b.reelPlays += p.ig_reels_plays ?? 0;
        if (p.ig_skip_rate != null) {
          b.skipRateSum += p.ig_skip_rate;
          b.skipCount++;
        }
      }

      const totalPosts = Math.max(1, Object.values(buckets).reduce((s, b) => s + b.posts, 0));

      const formats: IGFormatStat[] = ORDER
        .filter((t) => buckets[t].posts > 0)
        .map((t) => {
          const b = buckets[t];
          const viewBase = t === 'Reels' ? b.reelPlays : b.views;
          const avgViews = b.posts > 0 ? Math.round(viewBase / b.posts) : 0;
          const avgLikes = b.posts > 0 ? Math.round(b.likes / b.posts) : 0;
          const avgSaves = b.posts > 0 ? Math.round(b.saves / b.posts) : 0;
          const qweBase = Math.max(1, b.views || b.reelPlays);
          const qwe = ((b.saves * 3 + b.comments * 2 + b.likes * 0.5) / qweBase) * 100;
          const retentionPct =
            t === 'Reels' && b.skipCount > 0
              ? Math.max(0, Math.round((1 - b.skipRateSum / b.skipCount) * 100))
              : null;
          return {
            type: t,
            posts: b.posts,
            avgViews,
            avgLikes,
            avgSaves,
            qwe,
            retentionPct,
            sharePct: Math.round((b.posts / totalPosts) * 100),
          };
        });

      return { formats, hasRealData: true };
    })(), 'IG format breakdown'),
  });

  return {
    ...(data ?? EMPTY),
    loading: !!userKey && isPending,
  };
}
