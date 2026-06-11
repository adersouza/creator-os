import { useEffect, useState } from 'react';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';
import { createHookCache } from '@/hooks/_hookCache';
import { fetchConnectedAccounts } from '@/hooks/useConnectedAccounts';
import { queryClient } from '@/lib/queryClient';
import { queryKeys } from '@/lib/queryKeys';
import type { AccountScopeValue } from '@/stores/useAccountScopeStore';

export interface TopBottomPost {
  id: string;
  platform: 'threads' | 'instagram';
  accountId: string;
  username: string | null;
  content: string;
  publishedAt: string;
  permalink: string | null;
  views: number;
  reach: number;
  likes: number;
  comments: number;
  shares: number;
  saves: number;
  /** Total engagement (likes + comments + shares + saves). */
  engagement: number;
  /** ER × 100 — saves & comments × multipliers. */
  engagementRate: number | null;
}

export interface TopBottomState {
  top: TopBottomPost[];
  bottom: TopBottomPost[];
  isLoading: boolean;
  hasError: boolean;
}

interface PostRow {
  id: string;
  platform: string | null;
  account_id: string | null;
  instagram_account_id: string | null;
  content: string | null;
  published_at: string | null;
  permalink: string | null;
  views_count: number | null;
  ig_reach: number | null;
  likes_count: number | null;
  ig_comment_count: number | null;
  replies_count: number | null;
  ig_shares: number | null;
  shares_count: number | null;
  ig_saved: number | null;
}

const cache = createHookCache<TopBottomState>();
const EMPTY: TopBottomState = { top: [], bottom: [], isLoading: true, hasError: false };

const cacheKey = (
  user: string | null,
  days: number,
  platform: 'all' | 'threads' | 'instagram',
  scopedAccount: AccountScopeValue | null,
  limit: number,
) =>
  user
    ? `${user}:${days}:${platform}:${scopedAccount?.id ?? 'fleet'}:${limit}`
    : null;

function normalize(row: PostRow, usernameById: Map<string, string>): TopBottomPost {
  const isIg = row.platform === 'instagram';
  const accountId = (isIg ? row.instagram_account_id : row.account_id) ?? '';
  const views = row.views_count ?? 0;
  const reach = row.ig_reach ?? views;
  const likes = row.likes_count ?? 0;
  const comments = isIg ? row.ig_comment_count ?? 0 : row.replies_count ?? 0;
  const shares = isIg ? row.ig_shares ?? 0 : row.shares_count ?? 0;
  const saves = row.ig_saved ?? 0;
  const engagement = likes + comments + shares + saves;
  const engagementRate = reach > 0 ? Math.round((engagement / reach) * 10000) / 100 : null;
  return {
    id: row.id,
    platform: isIg ? 'instagram' : 'threads',
    accountId,
    username: usernameById.get(accountId) ?? null,
    content: row.content ?? '',
    publishedAt: row.published_at ?? '',
    permalink: row.permalink,
    views,
    reach,
    likes,
    comments,
    shares,
    saves,
    engagement,
    engagementRate,
  };
}

export interface UseTopBottomPostsArgs {
  days: number;
  platform: 'all' | 'threads' | 'instagram';
  scopedAccount?: AccountScopeValue | null | undefined;
  accountIds?: string[] | undefined;
  groupId?: string | null | undefined;
  limit?: number | undefined;
}

/**
 * Top + bottom N posts within a window, ranked by engagement (likes + comments
 * + shares + saves). Direct Supabase query — no new endpoint required.
 *
 * `top` is sorted desc by engagement, `bottom` is the lowest-engagement set
 * among posts that have at least 1 view (so genuinely bombed — not just
 * unsynced or pre-publish drafts).
 */
export function useTopBottomPosts(args: UseTopBottomPostsArgs): TopBottomState {
  const { days, platform, scopedAccount = null, accountIds, groupId = null, limit = 5 } = args;
  const authUser = useAuthUser();
  const userKey = authUser?.id ?? null;
  const [state, setState] = useState<TopBottomState>(() => {
    const cached = cache.get(`${cacheKey(userKey, days, platform, scopedAccount, limit)}:${groupId ?? 'all'}:${accountIds?.join(',') ?? 'fleet'}`);
    return cached ? { ...cached, isLoading: false, hasError: false } : EMPTY;
  });

  useEffect(() => {
    let cancelled = false;
    if (!authUser) return;

    const key = `${cacheKey(userKey, days, platform, scopedAccount, limit)}:${groupId ?? 'all'}:${accountIds?.join(',') ?? 'fleet'}`;
    const cached = cache.get(key);
    if (cached) setState({ ...cached, isLoading: false, hasError: false });
    else setState({ top: [], bottom: [], isLoading: true, hasError: false });
    if (cache.isFresh(key)) return;

    (async () => {
      try {
        const cutoff = new Date(Date.now() - days * 86_400_000).toISOString();
        const select =
          'id, platform, account_id, instagram_account_id, content, published_at, permalink, ' +
          'views_count, ig_reach, likes_count, ig_comment_count, replies_count, ig_shares, shares_count, ig_saved';

        let query = supabase
          .from('posts')
          .select(select)
          .eq('user_id', authUser.id)
          .eq('status', 'published')
          .gte('published_at', cutoff)
          .order('published_at', { ascending: false })
          .limit(500);

        if (platform !== 'all') query = query.eq('platform', platform);
        if (scopedAccount) {
          if (scopedAccount.platform === 'threads') {
            query = query.eq('account_id', scopedAccount.id);
          } else {
            query = query.eq('instagram_account_id', scopedAccount.id);
          }
        }

        const [postsRes, accounts] = await Promise.all([
          query,
          queryClient.fetchQuery({
            queryKey: queryKeys.accounts.connected(authUser.id),
            staleTime: 5 * 60_000,
            gcTime: 15 * 60_000,
            queryFn: () => fetchConnectedAccounts(authUser.id),
          }),
        ]);

        if (cancelled) return;
        if (postsRes.error) throw postsRes.error;

        const usernameById = new Map<string, string>();
        for (const account of accounts) {
          usernameById.set(account.id, account.handle.replace(/^@/, ''));
        }

        const rows = (postsRes.data ?? []) as unknown as PostRow[];
        const selectedAccountIds = scopedAccount
          ? null
          : accountIds && accountIds.length > 0
            ? new Set(accountIds)
            : null;
        const normalized = rows
          .map((r) => normalize(r, usernameById))
          .filter((post) =>
            (platform === 'all' || post.platform === platform) &&
            (!selectedAccountIds || selectedAccountIds.has(post.accountId)),
          );
        const ranked = [...normalized].sort((a, b) => b.engagement - a.engagement);
        const top = ranked.slice(0, limit);
        const bottomCandidates = normalized.filter((p) => p.views > 0);
        const bottom = [...bottomCandidates]
          .sort((a, b) => a.engagement - b.engagement)
          .slice(0, limit);

        const next: TopBottomState = { top, bottom, isLoading: false, hasError: false };
        cache.set(key, next);
        setState(next);
      } catch {
        if (cancelled) return;
        setState((prev) => ({
          ...prev,
          isLoading: false,
          hasError: prev.top.length === 0 && prev.bottom.length === 0,
        }));
      }
    })();

    return () => { cancelled = true; };
  }, [userKey, days, platform, authUser, scopedAccount, accountIds, groupId, limit]);

  return state;
}
