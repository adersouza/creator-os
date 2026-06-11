// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';

/**
 * Reply Chain Pulse — distribution of Threads posts by conversation depth.
 *
 * Depth semantics (set by the backend syncReplyChainForPost cron):
 *   1 = root only, no replies
 *   2 = one direct reply
 *   3 = reply-to-a-reply
 *   N = longest chain reached
 */

export type DepthBucket = {
  depth: string;
  count: number;
};

interface State {
  buckets: DepthBucket[];
  deepThreads: number;
  loading: boolean;
  hasRealData: boolean;
}

const MIN_POSTS_WITH_DEPTH = 20;

function timeframeDaysToCutoff(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  d.setHours(0, 0, 0, 0);
  return d.toISOString();
}

function toBucketLabel(depth: number): DepthBucket['depth'] {
  const turns = depth - 1;
  if (turns <= 0) return '0 turns';
  if (turns === 1) return '1 turn';
  if (turns === 2) return '2 turns';
  if (turns === 3) return '3 turns';
  return '4+ turns';
}

const EMPTY_BUCKETS: DepthBucket[] = [
  { depth: '0 turns', count: 0 },
  { depth: '1 turn', count: 0 },
  { depth: '2 turns', count: 0 },
  { depth: '3 turns', count: 0 },
  { depth: '4+ turns', count: 0 },
];

const EMPTY = { buckets: EMPTY_BUCKETS, deepThreads: 0, hasRealData: false };

export function useReplyChainDistribution(
  timeframeDays: number,
  accountId: string | null = null,
  accountIds?: string[] | undefined,
  groupId?: string | null | undefined,
): State {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending } = useQuery({
    queryKey: [
      'replyChainDistribution',
      userKey,
      timeframeDays,
      accountId ?? 'all',
      groupId ?? 'all',
      accountIds?.join(',') ?? null,
    ],
    enabled: !!userKey,
    // Historical reply-depth distribution can be mounted by multiple analytics
    // panels; staleTime prevents redundant fetches on every remount.
    staleTime: 5 * 60_000,
    gcTime: 15 * 60_000,
    queryFn: async () => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return EMPTY;

      const since = timeframeDaysToCutoff(timeframeDays);
      let query = supabase
        .from('posts')
        .select('reply_depth')
        .eq('user_id', user.id)
        .eq('platform', 'threads')
        .eq('status', 'published')
        .gte('published_at', since)
        .not('threads_post_id', 'is', null);
      if (accountId) query = query.eq('account_id', accountId);
      else if (accountIds && accountIds.length > 0) query = query.in('account_id', accountIds);

      const { data, error } = await query;

      if (error) throw error;

      const rows = data ?? [];
      const withDepth = rows.filter((r): r is { reply_depth: number } => typeof r.reply_depth === 'number');

      if (withDepth.length < MIN_POSTS_WITH_DEPTH) return EMPTY;

      const counts: Record<DepthBucket['depth'], number> = {
        '0 turns': 0,
        '1 turn': 0,
        '2 turns': 0,
        '3 turns': 0,
        '4+ turns': 0,
      };
      let deep = 0;
      for (const r of withDepth) {
        const bucket = toBucketLabel(r.reply_depth);
        counts[bucket]!++;
        if (r.reply_depth >= 5) deep++;
      }

      return {
        buckets: [
          { depth: '0 turns', count: counts['0 turns']! },
          { depth: '1 turn', count: counts['1 turn']! },
          { depth: '2 turns', count: counts['2 turns']! },
          { depth: '3 turns', count: counts['3 turns']! },
          { depth: '4+ turns', count: counts['4+ turns']! },
        ],
        deepThreads: deep,
        hasRealData: true,
      };
    },
  });

  return {
    ...(data ?? EMPTY),
    loading: !!userKey && isPending,
  };
}
