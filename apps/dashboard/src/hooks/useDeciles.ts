// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';
import type { FleetMetricsPlatform } from '@/hooks/useFleetMetrics';

export interface DecilePost {
  hook: string;
  time: string;
  type: string;
}

export interface DecilesState {
  top: DecilePost[];
  bottom: DecilePost[];
  hasRealData: boolean;
  loading: boolean;
}

export interface DecilesAccountScope {
  accountId: string;
  accountPlatform: 'threads' | 'instagram';
}

const MIN_POSTS = 20;
const MIN_REACH = 50;
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

function eqsForPost(row: {
  likes_count: number | null;
  replies_count: number | null;
  reposts_count: number | null;
  quotes_count: number | null;
  ig_saved: number | null;
  ig_comment_count: number | null;
  views_count: number | null;
  ig_reach: number | null;
}): number {
  const reach = Math.max(row.ig_reach ?? row.views_count ?? 0, MIN_REACH);
  const weighted =
    (row.likes_count ?? 0) * 1 +
    (row.replies_count ?? 0) * 2 +
    (row.reposts_count ?? 0) * 3 +
    (row.quotes_count ?? 0) * 2 +
    (row.ig_saved ?? 0) * 3 +
    (row.ig_comment_count ?? 0) * 2;
  return (weighted / reach) * 100;
}

function firstLine(content: string | null): string {
  if (!content) return '(no caption)';
  const first = content.split('\n')[0]!.trim();
  return first.length > 55 ? `${first.slice(0, 52)}…` : first;
}

function formatTime(publishedAt: string): string {
  const d = new Date(publishedAt);
  const day = DAYS[d.getDay()];
  const h = d.getHours();
  const ampm = h >= 12 ? 'PM' : 'AM';
  const h12 = h === 0 ? 12 : h > 12 ? h - 12 : h;
  return `${day} ${h12} ${ampm}`;
}

function formatType(platform: string | null, igMediaType: string | null, isCarousel: boolean | null): string {
  if (platform === 'instagram') {
    const mt = (igMediaType ?? '').toUpperCase();
    if (mt === 'REELS') return 'Reel';
    if (mt === 'STORIES') return 'Story';
    if (isCarousel || mt === 'CAROUSEL_ALBUM') return 'Carousel';
    return 'Feed';
  }
  if (platform === 'threads') {
    if (isCarousel) return 'Carousel';
    return 'Text';
  }
  return platform ?? 'Post';
}

function daysToCutoff(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  d.setHours(0, 0, 0, 0);
  return d.toISOString();
}

export function useDeciles(
  platform: FleetMetricsPlatform,
  timeframeDays: 7 | 30 | 90,
  accountScope?: DecilesAccountScope | null,
): DecilesState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending } = useQuery({
    queryKey: [
      'deciles',
      userKey,
      platform,
      timeframeDays,
      accountScope?.accountId ?? null,
      accountScope?.accountPlatform ?? null,
    ],
    enabled: !!userKey,
    staleTime: 1000 * 60 * 15,
    queryFn: async () => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return { top: [], bottom: [], hasRealData: false };

      const since = daysToCutoff(timeframeDays);

      let query = supabase
        .from('posts')
        .select(
          'content, platform, ig_media_type, is_carousel, published_at, likes_count, replies_count, reposts_count, quotes_count, ig_saved, ig_comment_count, views_count, ig_reach',
        )
        .eq('user_id', user.id)
        .eq('status', 'published')
        .gte('published_at', since)
        .not('published_at', 'is', null)
        .not('content', 'is', null);

      if (platform === 'threads') query = query.eq('platform', 'threads');
      if (platform === 'instagram') query = query.eq('platform', 'instagram');
      if (accountScope?.accountId) {
        const column = accountScope.accountPlatform === 'instagram' ? 'instagram_account_id' : 'account_id';
        query = query.eq(column, accountScope.accountId);
      }

      const { data: posts, error } = await query;
      if (error) throw error;
      if (!posts || posts.length < MIN_POSTS) return { top: [], bottom: [], hasRealData: false };

      const scored = posts
        .map((p) => ({ p, score: eqsForPost(p) }))
        .sort((a, b) => b.score - a.score);

      const decileSize = Math.max(1, Math.floor(scored.length * 0.1));
      const topPosts = scored.slice(0, decileSize);
      const bottomPosts = scored.slice(-decileSize);

      const toRow = ({ p }: { p: typeof posts[number] }): DecilePost => ({
        hook: firstLine(p.content),
        time: p.published_at ? formatTime(p.published_at) : '—',
        type: formatType(p.platform, p.ig_media_type, p.is_carousel),
      });

      return {
        top: topPosts.map(toRow),
        bottom: bottomPosts.map(toRow),
        hasRealData: true,
      };
    },
  });

  return {
    ...(data ?? { top: [], bottom: [], hasRealData: false }),
    loading: !!userKey && isPending,
  };
}
