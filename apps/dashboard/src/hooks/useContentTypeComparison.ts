import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';
import type { FleetMetricsPlatform } from '@/hooks/useFleetMetrics';

export interface ContentTypeRow {
  type: string;
  eqs: number;
  reach: string;
  posts: number;
}

export interface ContentTypeComparisonState {
  rows: ContentTypeRow[];
  hasRealData: boolean;
  loading: boolean;
}

export interface ContentTypeAccountScope {
  accountId: string;
  accountPlatform: 'threads' | 'instagram';
}

const MIN_POSTS = 5;

function daysToCutoff(days: 7 | 30 | 90): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  d.setHours(0, 0, 0, 0);
  return d.toISOString();
}

function formatReach(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function detectThreadsType(row: {
  media_type: string | null;
  is_carousel: boolean | null;
  media_urls: string[] | null;
  link_url: string | null;
}): string {
  if (row.link_url) return 'Link';
  const hasMedia = Array.isArray(row.media_urls) && row.media_urls.length > 0;
  const mt = (row.media_type ?? '').toUpperCase();
  if (row.is_carousel || mt === 'CAROUSEL_ALBUM') return 'Carousel';
  if (mt === 'VIDEO') return 'Text + Video';
  if (hasMedia) return 'Text + Image';
  return 'Pure Text';
}

function detectIGType(row: {
  ig_media_type: string | null;
  is_carousel: boolean | null;
}): string {
  const mt = (row.ig_media_type ?? '').toUpperCase();
  if (mt === 'REELS') return 'Reels';
  if (mt === 'STORIES') return 'Stories';
  if (row.is_carousel || mt === 'CAROUSEL_ALBUM') return 'Carousels';
  return 'Images';
}

export function useContentTypeComparison(
  platform: FleetMetricsPlatform,
  timeframeDays: 7 | 30 | 90,
  accountScope?: ContentTypeAccountScope | null,
): ContentTypeComparisonState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending } = useQuery({
    queryKey: [
      'contentTypeComparison',
      userKey,
      platform,
      timeframeDays,
      accountScope?.accountId ?? null,
      accountScope?.accountPlatform ?? null,
    ],
    enabled: !!userKey,
    queryFn: async () => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return { rows: [], hasRealData: false };

      const since = daysToCutoff(timeframeDays);

      let query = supabase
        .from('posts')
        .select(
          'platform, media_type, ig_media_type, is_carousel, media_urls, link_url, ' +
          'views_count, ig_reach, likes_count, replies_count, reposts_count, quotes_count, ig_saved, ig_shares, ig_comment_count',
        )
        .eq('user_id', user.id)
        .eq('status', 'published')
        .gte('published_at', since);

      if (platform !== 'all') query = query.eq('platform', platform === 'instagram' ? 'instagram' : 'threads');
      if (accountScope?.accountId) {
        const column = accountScope.accountPlatform === 'instagram' ? 'instagram_account_id' : 'account_id';
        query = query.eq(column, accountScope.accountId);
      }

      const { data: posts, error } = await query;
      if (error) throw error;
      if (!posts || posts.length < MIN_POSTS) return { rows: [], hasRealData: false };

      type PostRow = {
        platform: string | null;
        media_type: string | null;
        ig_media_type: string | null;
        is_carousel: boolean | null;
        media_urls: string[] | null;
        link_url: string | null;
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

      const buckets = new Map<string, { engRate: number; reach: number; count: number }>();

      for (const p of posts as unknown as PostRow[]) {
        const type =
          p.platform === 'instagram'
            ? detectIGType(p)
            : detectThreadsType(p);

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

        const entry = buckets.get(type) ?? { engRate: 0, reach: 0, count: 0 };
        entry.engRate += rate;
        entry.reach += reach;
        entry.count++;
        buckets.set(type, entry);
      }

      const rawRows = Array.from(buckets.entries())
        .filter(([, b]) => b.count >= 2)
        .map(([type, b]) => ({
          type,
          avgEngRate: b.count > 0 ? b.engRate / b.count : 0,
          reach: b.reach,
          posts: b.count,
        }));

      if (rawRows.length === 0) return { rows: [], hasRealData: false };

      const maxRate = Math.max(1, ...rawRows.map((r) => r.avgEngRate));

      const rows: ContentTypeRow[] = rawRows
        .sort((a, b) => b.avgEngRate - a.avgEngRate)
        .map((r) => ({
          type: r.type,
          eqs: Math.round((r.avgEngRate / maxRate) * 85),
          reach: formatReach(r.reach),
          posts: r.posts,
        }));

      return { rows, hasRealData: true };
    },
  });

  return {
    rows: data?.rows ?? [],
    hasRealData: data?.hasRealData ?? false,
    loading: !!userKey && isPending,
  };
}
