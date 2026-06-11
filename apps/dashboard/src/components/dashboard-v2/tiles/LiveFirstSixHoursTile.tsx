import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { NovaCard, NovaEmpty, NovaMiniStat } from "@/components/ui/NovaPrimitives";
import { Skeleton } from '@/components/ui/Skeleton';
import { useTopPosts, type TopPostRow, type TopPostsPlatform } from '@/hooks/useTopPosts';
import { useAuthUser } from '@/hooks/useAuthUser';
import { fetchConnectedAccounts } from '@/hooks/useConnectedAccounts';
import { queryClient } from '@/lib/queryClient';
import { queryKeys } from '@/lib/queryKeys';
import { supabase } from '@/services/supabase';
import type { AccountScopeValue } from '@/stores/useAccountScopeStore';
import type { Platform } from '../shared';
import { formatCompact } from '../shared';

interface Props {
  platform: Platform;
  scopedAccount?: AccountScopeValue | null | undefined;
}

interface LiveTopPostRow extends TopPostRow {
  mediaProductType?: string | null;
}

const HOUR_MS = 60 * 60 * 1000;
const SIX_HOURS_MS = 6 * HOUR_MS;
const LIVE_POST_LIMIT = 100;
const UNASSIGNED_COLOR = '#6B6B70';

function mapLiveRow(
  // biome-ignore lint/suspicious/noExplicitAny: Supabase string-select widens row shape
  row: any,
  meta: { handle: string; groupId: string | null; groupName: string; groupColor: string },
): LiveTopPostRow {
  const isIg = row.platform === 'instagram';
  return {
    id: String(row.id),
    platform: isIg ? 'instagram' : 'threads',
    caption: typeof row.content === 'string' ? row.content : '',
    mediaUrl: Array.isArray(row.media_urls) && row.media_urls.length ? String(row.media_urls[0]) : null,
    accountId: isIg ? row.instagram_account_id ?? null : row.account_id ?? null,
    accountHandle: meta.handle,
    groupId: meta.groupId,
    groupName: meta.groupName,
    groupColor: meta.groupColor,
    reach: isIg ? row.ig_reach ?? 0 : row.views_count ?? 0,
    sends: isIg ? row.ig_shares ?? 0 : row.shares_count ?? 0,
    saves: isIg ? row.ig_saved ?? 0 : 0,
    likes: row.likes_count ?? 0,
    comments: isIg ? row.ig_comment_count ?? 0 : row.replies_count ?? 0,
    publishedAt: String(row.published_at ?? row.created_at ?? ''),
    mediaProductType: typeof row.media_product_type === 'string' ? row.media_product_type : null,
  };
}

function useLiveRecentPosts(platform: TopPostsPlatform) {
  const authUser = useAuthUser();
  const userKey = authUser?.id ?? null;

  const { data, isPending, isError } = useQuery({
    queryKey: ['liveFirstSixHours', userKey, platform],
    enabled: !!userKey,
    staleTime: 60_000,
    queryFn: async (): Promise<LiveTopPostRow[]> => {
      if (!userKey) return [];
      const since = new Date(Date.now() - SIX_HOURS_MS).toISOString();

      const postsQuery = supabase
        .from('posts')
        .select(
          'id, platform, content, media_urls, account_id, instagram_account_id, published_at, created_at, ' +
            'likes_count, shares_count, replies_count, views_count, ig_saved, ig_shares, ig_comment_count, ig_reach, media_product_type',
        )
        .eq('user_id', userKey)
        .eq('status', 'published')
        .not('published_at', 'is', null)
        .gte('published_at', since)
        .order('published_at', { ascending: false })
        .limit(LIVE_POST_LIMIT);

      const scopedPostsQuery = platform === 'all'
        ? postsQuery
        : postsQuery.eq('platform', platform === 'ig' ? 'instagram' : 'threads');

      const [postsRes, connectedAccounts] = await Promise.all([
        scopedPostsQuery,
        queryClient.fetchQuery({
          queryKey: queryKeys.accounts.connected(userKey),
          staleTime: 5 * 60_000,
          gcTime: 15 * 60_000,
          queryFn: () => fetchConnectedAccounts(userKey),
        }),
      ]);

      if (postsRes.error) throw postsRes.error;

      const metaById = new Map<string, { handle: string; groupId: string | null; groupName: string; groupColor: string }>();
      for (const account of connectedAccounts) {
        metaById.set(account.id, {
          handle: account.handle.replace(/^@/, ''),
          groupId: account.groupId,
          groupName: account.groupName,
          groupColor: account.groupColor,
        });
      }

      // biome-ignore lint/suspicious/noExplicitAny: Supabase string-select widens row shape
      const rows = ((postsRes.data ?? []) as any[]).map((row) => {
        const accountId = row.platform === 'instagram' ? row.instagram_account_id : row.account_id;
        const meta = accountId
          ? metaById.get(accountId) ?? { handle: 'unknown', groupId: null, groupName: 'Unassigned', groupColor: UNASSIGNED_COLOR }
          : { handle: 'unknown', groupId: null, groupName: 'Unassigned', groupColor: UNASSIGNED_COLOR };
        return mapLiveRow(row, meta);
      });

      return rows.sort((a, b) => Date.parse(b.publishedAt) - Date.parse(a.publishedAt));
    },
  });

  return {
    posts: data ?? [],
    isLoading: !!userKey && isPending,
    hasError: !!userKey && isError,
  };
}

/**
 * Live · first 6 hours (mockup new-widgets-2026 #1).
 *
 * Replaces TodaysLeadPostTile. Surfaces the most recent post within the
 * 6h post-publish window — the boost-decision window for Meta Ads.
 * Each metric (views/sends/saves/likes) is shown vs its 30d median for
 * fleet-relative context. "Outperforming" callout when sends/reach
 * crosses the 90th percentile band.
 */
export function LiveFirstSixHoursTile({ platform, scopedAccount = null }: Props) {
  const fleetPlatform: TopPostsPlatform = platform;
  const scopedPlatform = scopedAccount
    ? scopedAccount.platform === 'instagram'
      ? 'ig'
      : 'threads'
    : null;
  const platformMismatch =
    scopedPlatform != null && platform !== 'all' && platform !== scopedPlatform;
  const recent = useLiveRecentPosts(fleetPlatform);
  const [liveIndex, setLiveIndex] = useState(0);
  // Fetch 30d to get a healthy distribution for median computation.
  const thirty = useTopPosts('30d', fleetPlatform);

  const live = useMemo(() => {
    const safeIndex = recent.posts.length > 0 ? Math.min(liveIndex, recent.posts.length - 1) : 0;
    return recent.posts[safeIndex] ?? null;
  }, [liveIndex, recent.posts]);
  const safeLiveIndex = recent.posts.length > 0 ? Math.min(liveIndex, recent.posts.length - 1) : 0;

  const medians = useMemo(() => {
    const valid = thirty.posts.filter((p) => p.reach > 0);
    if (valid.length === 0) return null;
    const med = (vals: number[]) => {
      if (vals.length === 0) return 0;
      const sorted = [...vals].sort((a, b) => a - b);
      return sorted[Math.floor(sorted.length / 2)];
    };
    return {
      reach: med(valid.map((p) => p.reach)),
      sends: med(valid.map((p) => p.sends)),
      saves: med(valid.map((p) => p.saves)),
      likes: med(valid.map((p) => p.likes)),
    };
  }, [thirty.posts]);

  const sendsPerReach = useMemo(() => {
    if (!live || live.reach === 0) return null;
    return live.sends / live.reach;
  }, [live]);

  const sendsPerReachPercentile = useMemo(() => {
    if (!live || sendsPerReach == null) return null;
    const sample = thirty.posts
      .filter((p) => p.reach > 0 && p.id !== live.id)
      .map((p) => p.sends / p.reach)
      .sort((a, b) => a - b);
    if (sample.length === 0) return null;
    let below = 0;
    for (const v of sample) {
      if (v < sendsPerReach) below += 1;
    }
    return Math.round((below / sample.length) * 100);
  }, [live, sendsPerReach, thirty.posts]);

  const isOutperforming =
    sendsPerReachPercentile != null && sendsPerReachPercentile >= 90;

  const ageLabel = useMemo(() => {
    if (!live) return null;
    const t = Date.parse(live.publishedAt);
    if (!Number.isFinite(t)) return null;
    const ageMin = Math.max(0, Math.floor((Date.now() - t) / 60000));
    const h = Math.floor(ageMin / 60);
    const m = ageMin % 60;
    if (h === 0) return `${m}m post-publish`;
    return `${h}h ${m}m post-publish`;
  }, [live]);

  return (
    <NovaCard
      variant="compact"
      eyebrow="Live · first 6 hours"
      title="Live post pulse"
      description="Recent posts in the boost-decision window with 30d median context."
      action={<Badge variant="outline">{ageLabel ? ageLabel : 'No live post'}</Badge>}
    >
        {platformMismatch && scopedPlatform ? (
          <ScopeMismatchState accountPlatform={scopedPlatform} selectedPlatform={platform} />
        ) : live ? (
          <div className="flex" style={{ gap: 16, alignItems: 'flex-start' }}>
            <Thumb mediaUrl={live.mediaUrl} platform={live.platform} mediaProductType={live.mediaProductType ?? null} />
            <div className="flex-1 min-w-0" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div
                style={{
                  fontSize: 13.5,
                  lineHeight: 1.4,
                  display: '-webkit-box',
                  WebkitLineClamp: 2,
                  WebkitBoxOrient: 'vertical',
                  overflow: 'hidden',
                }}
              >
                {live.caption?.trim() || '— no caption —'}
              </div>
              <div className="font-mono text-[11px] uppercase tracking-[0.08em] text-muted-foreground">
                @{live.accountHandle} · {new Date(live.publishedAt).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}
              </div>
              {recent.posts.length > 1 ? (
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    disabled={safeLiveIndex === 0}
                    onClick={() => setLiveIndex((i) => Math.max(0, i - 1))}
                    aria-label="Previous live post"
                  >
                    <ChevronLeft className="size-4" />
                  </Button>
                  <span className="font-mono text-xs text-muted-foreground">
                    {safeLiveIndex + 1} of {recent.posts.length}
                  </span>
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    disabled={safeLiveIndex >= recent.posts.length - 1}
                    onClick={() => setLiveIndex((i) => Math.min(recent.posts.length - 1, i + 1))}
                    aria-label="Next live post"
                  >
                    <ChevronRight className="size-4" />
                  </Button>
                </div>
              ) : null}

              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(4, 1fr)',
                  gap: 10,
                  marginTop: 4,
                }}
              >
                <NovaMiniStat
                  label="Views"
                  value={formatCompact(live.reach)}
                  description={formatMetricDelta(live.reach, medians?.reach ?? null)}
                  tone={metricTone(live.reach, medians?.reach ?? null)}
                  size="compact"
                />
                <NovaMiniStat
                  label="Sends"
                  value={formatCompact(live.sends)}
                  description={formatMetricDelta(live.sends, medians?.sends ?? null)}
                  tone={metricTone(live.sends, medians?.sends ?? null)}
                  size="compact"
                />
                <NovaMiniStat
                  label="Saves"
                  value={formatCompact(live.saves)}
                  description={formatMetricDelta(live.saves, medians?.saves ?? null)}
                  tone={metricTone(live.saves, medians?.saves ?? null)}
                  size="compact"
                />
                <NovaMiniStat
                  label="Likes"
                  value={formatCompact(live.likes)}
                  description={formatMetricDelta(live.likes, medians?.likes ?? null)}
                  tone={metricTone(live.likes, medians?.likes ?? null)}
                  size="compact"
                />
              </div>

              {isOutperforming ? (
                <div
                  style={{
                    marginTop: 4,
                    padding: '8px 12px',
                    borderRadius: 6,
                    background: 'color-mix(in srgb, var(--color-health-good) 12%, transparent)',
                    border: '1px solid color-mix(in srgb, var(--color-health-good) 35%, transparent)',
                    fontSize: 11.5,
                    color: 'var(--color-foreground)',
                    lineHeight: 1.4,
                  }}
                >
                  <strong style={{ color: 'var(--color-health-good)' }}>Outperforming.</strong>{' '}
                  Sends-per-reach in the top {Math.max(1, 100 - (sendsPerReachPercentile ?? 0))}% of last 30 days.
                  High-performer candidate.
                </div>
              ) : null}
              <div className="font-mono text-[11px] text-muted-foreground">
                Delta color: red below median · neutral 0–10% · oxblood 10–50% · green &gt;50%.
              </div>
            </div>
          </div>
        ) : (
          <LivePostEmpty isLoading={recent.isLoading} hasError={recent.hasError} />
        )}
    </NovaCard>
  );
}

function mediaLabel(platform: 'threads' | 'instagram', mediaProductType: string | null): string | null {
  const raw = mediaProductType?.toLowerCase() ?? '';
  if (raw.includes('reel')) return 'Reel';
  if (raw.includes('carousel')) return 'Carousel';
  if (raw.includes('image') || raw.includes('photo')) return 'Image';
  if (platform === 'instagram' && raw) return 'Post';
  return platform === 'instagram' && mediaProductType == null ? 'Post' : null;
}

function ScopeMismatchState({
  accountPlatform,
  selectedPlatform,
}: {
  accountPlatform: 'threads' | 'ig';
  selectedPlatform: Platform;
}) {
  const accountLabel = accountPlatform === 'ig' ? 'Instagram' : 'Threads';
  const selectedLabel =
    selectedPlatform === 'ig'
      ? 'Instagram'
      : selectedPlatform === 'threads'
        ? 'Threads'
        : 'All platforms';
  return (
    <NovaEmpty
      title={`Selected account is on ${accountLabel}`}
      description={`Current live-post filter is ${selectedLabel}. Switch to ${accountLabel} to see live posts for this account.`}
    />
  );
}

function Thumb({ mediaUrl, platform, mediaProductType }: { mediaUrl: string | null; platform: 'threads' | 'instagram'; mediaProductType: string | null }) {
  const label = mediaLabel(platform, mediaProductType);
  return (
    <div
      style={{
        width: 110,
        height: 110,
        flexShrink: 0,
        borderRadius: 8,
        overflow: 'hidden',
        position: 'relative',
        background: mediaUrl
          ? 'var(--color-background)'
          : 'linear-gradient(135deg, var(--color-oxblood-bar), var(--color-gold))',
      }}
    >
      {mediaUrl ? (
        <img
          src={mediaUrl}
          alt=""
          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
          loading="lazy"
          decoding="async"
        />
      ) : null}
      {label ? (
        <div
          aria-hidden="true"
          style={{
            position: 'absolute',
            bottom: 6,
            left: 6,
            font: '600 9px var(--font-mono)',
            color: 'color-mix(in_srgb,var(--color-card-elevated)_85%,transparent)',
            background: 'color-mix(in_srgb,var(--color-foreground)_55%,transparent)',
            padding: '2px 6px',
            borderRadius: 3,
            letterSpacing: '0.05em',
            textTransform: 'uppercase',
          }}
        >
          {label}
        </div>
      ) : null}
    </div>
  );
}

function metricDelta(value: number, median: number | null) {
  const delta = median != null && median > 0 ? Math.round(((value - median) / median) * 100) : null;
  return delta;
}

function formatMetricDelta(value: number, median: number | null) {
  const delta = metricDelta(value, median);
  return delta == null ? 'no median' : `${delta >= 0 ? '+' : ''}${delta}% vs 30d med`;
}

function metricTone(value: number, median: number | null): "default" | "primary" | "success" | "danger" {
  const delta = metricDelta(value, median);
  if (delta == null || delta < 10 && delta >= 0) return "default";
  if (delta > 50) return "success";
  return delta >= 10 ? "primary" : "danger";
}

function LivePostEmpty({ isLoading, hasError }: { isLoading: boolean; hasError: boolean }) {
  if (isLoading) {
    return (
      <div className="rounded-lg border border-border bg-muted/35 p-4">
        <div className="flex items-stretch gap-3">
          <Skeleton className="h-20 w-20 shrink-0 rounded-lg" />
          <div className="min-w-0 flex-1">
            <Skeleton className="h-3 w-4/5" />
            <Skeleton className="mt-2 h-3 w-1/2" />
            <div className="mt-4 grid grid-cols-4 gap-2">
              {['Views', 'Sends', 'Saves', 'Likes'].map((label) => (
                <div key={label} className="rounded-md border border-border bg-card p-2">
                  <div className="font-mono text-[9px] uppercase tracking-[0.08em] text-muted-foreground">
                    {label}
                  </div>
                  <Skeleton className="mt-2 h-2 w-3/5" />
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <NovaEmpty
      title={hasError ? 'Top posts unavailable' : 'No posts in the last 6 hours'}
      description={
        hasError
          ? 'Refresh the dashboard to retry the leaderboard query.'
          : 'The next live post will appear with 30d median deltas and high-performer context.'
      }
    />
  );
}
