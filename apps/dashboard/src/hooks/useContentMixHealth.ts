// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useQuery } from '@tanstack/react-query';
import { useAuthUser } from '@/hooks/useAuthUser';
import { getApiAuthHeaders } from '@/lib/apiAuth';
import { apiUrl } from '@/lib/apiUrl';
import { supabase } from '@/services/supabase';

export interface ContentMixDelta {
  current: number;
  previous: number;
  delta: number;
  pctChange: number | null;
}

export type ContentMixMediaType = 'feed' | 'reels' | 'story' | string;
export type ContentMixMetric = 'reach' | 'views' | 'likes' | 'comments' | 'shares' | 'saves' | string;

export interface ContentMixResponse {
  current: Record<ContentMixMediaType, Record<ContentMixMetric, number>>;
  previous: Record<ContentMixMediaType, Record<ContentMixMetric, number>>;
  deltas: Record<ContentMixMediaType, Record<ContentMixMetric, ContentMixDelta>>;
  trail: Array<{
    weekStart: string;
    reelsPct: number;
    feedPct: number;
    storyPct: number;
    totalReach: number;
  }>;
}

interface ContentMixState extends ContentMixResponse {
  isLoading: boolean;
  hasError: boolean;
}

const EMPTY: ContentMixResponse = { current: {}, previous: {}, deltas: {}, trail: [] };

interface PostMixRow {
  instagram_account_id: string | null;
  published_at: string | null;
  media_type: string | null;
  ig_media_type: string | null;
  ig_reach: number | null;
  ig_views: number | null;
  likes_count: number | null;
  replies_count: number | null;
  ig_shares: number | null;
  shares_count: number | null;
  ig_saved: number | null;
}

function bucketFor(row: Pick<PostMixRow, 'media_type' | 'ig_media_type'>): 'reels' | 'feed' | 'story' {
  const raw = String(row.ig_media_type || row.media_type || '').toLowerCase();
  if (raw.includes('reel') || raw === 'video') return 'reels';
  if (raw.includes('stor')) return 'story';
  return 'feed';
}

function sumPosts(rows: PostMixRow[]): ContentMixResponse['current'] {
  const out: ContentMixResponse['current'] = {};
  for (const row of rows) {
    const bucket = bucketFor(row);
    out[bucket] = out[bucket] || {};
    out[bucket].reach = (out[bucket].reach || 0) + (row.ig_reach || 0);
    out[bucket].views = (out[bucket].views || 0) + (row.ig_views || 0);
    out[bucket].likes = (out[bucket].likes || 0) + (row.likes_count || 0);
    out[bucket].comments = (out[bucket].comments || 0) + (row.replies_count || 0);
    out[bucket].shares = (out[bucket].shares || 0) + (row.ig_shares || row.shares_count || 0);
    out[bucket].saves = (out[bucket].saves || 0) + (row.ig_saved || 0);
  }
  return out;
}

function buildDeltas(
  current: ContentMixResponse['current'],
  previous: ContentMixResponse['previous'],
): ContentMixResponse['deltas'] {
  const deltas: ContentMixResponse['deltas'] = {};
  const mediaTypes = new Set([...Object.keys(current), ...Object.keys(previous)]);
  for (const mediaType of mediaTypes) {
    deltas[mediaType] = {};
    const metrics = new Set([
      ...Object.keys(current[mediaType] || {}),
      ...Object.keys(previous[mediaType] || {}),
    ]);
    for (const metric of metrics) {
      const c = current[mediaType]?.[metric] || 0;
      const p = previous[mediaType]?.[metric] || 0;
      deltas[mediaType][metric] = {
        current: c,
        previous: p,
        delta: c - p,
        pctChange: p > 0 ? ((c - p) / p) * 100 : null,
      };
    }
  }
  return deltas;
}

function weekStartIso(iso: string): string {
  const d = new Date(iso);
  const day = d.getUTCDay();
  d.setUTCDate(d.getUTCDate() - ((day + 6) % 7));
  return d.toISOString().split('T')[0]!;
}

function trailPoint(weekStart: string, rows: PostMixRow[]): ContentMixResponse['trail'][number] | null {
  const buckets = sumPosts(rows);
  const reels = buckets.reels?.reach ?? 0;
  const feed = buckets.feed?.reach ?? 0;
  const story = buckets.story?.reach ?? 0;
  const totalReach = reels + feed + story;
  if (totalReach <= 0) return null;
  return {
    weekStart,
    reelsPct: (reels / totalReach) * 100,
    feedPct: (feed / totalReach) * 100,
    storyPct: (story / totalReach) * 100,
    totalReach,
  };
}

function hasReach(data: ContentMixResponse): boolean {
  return (
    (data.current.reels?.reach ?? 0) +
      (data.current.feed?.reach ?? 0) +
      (data.current.story?.reach ?? 0)
  ) > 0;
}

async function fetchContentMix(
  accountId: string | null,
  accountIds?: string[],
  periodDays = 30,
  groupId?: string | null,
): Promise<ContentMixResponse> {
  const params = new URLSearchParams();
  if (accountId) params.set('accountId', accountId);
  else if (groupId) params.set('groupId', groupId);
  else if (accountIds && accountIds.length > 0) params.set('accountIds', accountIds.join(','));
  params.set('periodDays', String(periodDays));
  const qs = params.toString();
  const url = apiUrl(`/api/analytics?action=content-type-trend${qs ? `&${qs}` : ''}`);
  const response = await fetch(url, {
    headers: await getApiAuthHeaders(),
  });
  if (!response.ok) throw new Error('Failed to fetch content mix');
  const data = (await response.json()) as ContentMixResponse;
  return {
    current: data.current ?? {},
    previous: data.previous ?? {},
    deltas: data.deltas ?? {},
    trail: data.trail ?? [],
  };
}

async function fetchPostBackedContentMix(
  userId: string,
  accountId: string | null,
  accountIds?: string[],
  periodDays = 30,
): Promise<ContentMixResponse> {
  const today = new Date();
  const currentStart = new Date(today);
  currentStart.setDate(currentStart.getDate() - periodDays);
  const previousStart = new Date(today);
  previousStart.setDate(previousStart.getDate() - periodDays * 2);
  const trailStart = new Date(today);
  trailStart.setDate(trailStart.getDate() - 84);

  let query = supabase
    .from('posts')
    .select('instagram_account_id, published_at, media_type, ig_media_type, ig_reach, ig_views, likes_count, replies_count, ig_shares, shares_count, ig_saved')
    .eq('user_id', userId)
    .eq('platform', 'instagram')
    .eq('status', 'published')
    .gte('published_at', trailStart.toISOString())
      .lte('published_at', today.toISOString());
  if (accountId) query = query.eq('instagram_account_id', accountId);

  const { data, error } = await query;
  if (error) throw error;

  const selectedAccountIds = !accountId && accountIds && accountIds.length > 0
    ? new Set(accountIds)
    : null;
  const rows = ((data ?? []) as PostMixRow[]).filter((row) =>
    row.published_at &&
    (!selectedAccountIds || (row.instagram_account_id && selectedAccountIds.has(row.instagram_account_id))),
  );
  const current = sumPosts(
    rows.filter((row) => new Date(row.published_at as string) >= currentStart),
  );
  const previous = sumPosts(
    rows.filter((row) => {
      const publishedAt = new Date(row.published_at as string);
      return publishedAt >= previousStart && publishedAt < currentStart;
    }),
  );

  const byWeek = new Map<string, PostMixRow[]>();
  for (const row of rows) {
    const weekStart = weekStartIso(row.published_at as string);
    const weekRows = byWeek.get(weekStart) ?? [];
    weekRows.push(row);
    byWeek.set(weekStart, weekRows);
  }

  const trail = Array.from(byWeek.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([weekStart, weekRows]) => trailPoint(weekStart, weekRows))
    .filter((point): point is ContentMixResponse['trail'][number] => point != null)
    .slice(-12);

  return { current, previous, deltas: buildDeltas(current, previous), trail };
}

/**
 * IG content-mix health — WoW deltas for reels / feed / story. Diffs
 * account_analytics.ig_content_type_breakdown JSONB snapshots that
 * daily-orchestrator already writes. Instagram accounts only.
 */
export function useContentMixHealth(
  accountId: string | null = null,
  accountIds?: string[],
  periodDays = 30,
  groupId?: string | null,
): ContentMixState {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending, isError } = useQuery<ContentMixResponse>({
    queryKey: ['contentMix', userKey, accountId, groupId ?? null, accountIds?.join(',') ?? null, periodDays],
    enabled: !!userKey,
    staleTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
    queryFn: async () => {
      if (groupId && !accountId) {
        return fetchContentMix(accountId, undefined, periodDays, groupId);
      }
      const postData = await fetchPostBackedContentMix(userKey as string, accountId, accountIds, periodDays);
      if (hasReach(postData)) return postData;
      if (!accountId && !groupId && accountIds && accountIds.length > 20) return postData;
      return fetchContentMix(accountId, accountIds, periodDays, groupId).catch(() => postData);
    },
  });

  return {
    ...(data ?? EMPTY),
    isLoading: !!userKey && isPending,
    hasError: !!userKey && isError,
  };
}
