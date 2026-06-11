import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/services/supabase';
import { useAuthUser } from '@/hooks/useAuthUser';
import { withAnalyticsQueryTimeout } from '@/lib/analyticsQueryTimeout';

/**
 * Vanity Engagement — accounts whose IG posts earn likes at an outsized
 * rate vs quality actions (DM shares + saves). Likes are passive; sends are
 * Meta's confirmed discovery signal. An account with 40:1 likes-to-quality
 * is getting scrolled past, not shared or saved — content reads well but isn't
 * shareable.
 */

export interface VanityAccount {
  accountId: string;
  handle: string;
  platform: 'instagram';
  likes: number;
  sends: number;
  saves: number;
  ratio: number;
}

interface State {
  accounts: VanityAccount[];
  fleetAvgRatio: number;
  hasRealData: boolean;
  loading: boolean;
}

const MIN_ACCOUNTS_FOR_FLEET_BASELINE = 3;
const MIN_LIKES_FOR_SAMPLE = 200;
const MIN_RATIO_TO_FLAG = 20;
const FLEET_MULTIPLE_TO_FLAG = 2;

function daysToCutoff(days: 7 | 30 | 90): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  d.setHours(0, 0, 0, 0);
  return d.toISOString();
}

const EMPTY: Omit<State, 'loading'> = {
  accounts: [],
  fleetAvgRatio: 0,
  hasRealData: false,
};

export function useVanityAccounts(
  timeframeDays: 7 | 30 | 90,
  instagramAccountId?: string | null,
  accountIds?: string[],
): State {
  const authUser = useAuthUser();
  const userKey = authUser ? authUser.id : null;

  const { data, isPending } = useQuery({
    queryKey: ['vanityAccounts', userKey, timeframeDays, instagramAccountId ?? null, accountIds?.join(',') ?? null],
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
        .select('account_id, instagram_account_id, likes_count, ig_shares, ig_saved')
        .eq('user_id', user.id)
        .eq('platform', 'instagram')
        .eq('status', 'published')
        .gte('published_at', since);
      if (instagramAccountId) query = query.eq('instagram_account_id', instagramAccountId);
      else if (accountIds && accountIds.length > 0) query = query.in('instagram_account_id', accountIds);

      const { data: posts, error } = await query;
      if (error) throw error;
      if (!posts) return EMPTY;

      type PostRow = {
        account_id: string | null;
        instagram_account_id: string | null;
        likes_count: number | null;
        ig_shares: number | null;
        ig_saved: number | null;
      };
      const perAccount = new Map<string, { likes: number; sends: number; saves: number }>();
      for (const p of posts as PostRow[]) {
        const id = p.instagram_account_id ?? p.account_id;
        if (!id) continue;
        const entry = perAccount.get(id) ?? { likes: 0, sends: 0, saves: 0 };
        entry.likes += p.likes_count ?? 0;
        entry.sends += p.ig_shares ?? 0;
        entry.saves += p.ig_saved ?? 0;
        perAccount.set(id, entry);
      }

      if (perAccount.size < MIN_ACCOUNTS_FOR_FLEET_BASELINE) return EMPTY;

      const ids = Array.from(perAccount.keys());
      const { data: accountRows, error: accountRowsError } = await supabase
        .from('instagram_accounts')
        .select('id, username, display_name')
        .in('id', ids);

      if (accountRowsError) throw accountRowsError;

      const handleById = new Map<string, string>();
      for (const row of (accountRows ?? []) as Array<{
        id: string;
        username: string | null;
        display_name: string | null;
      }>) {
        handleById.set(row.id, row.username ?? row.display_name ?? 'unknown');
      }

      let totalLikes = 0;
      let totalQuality = 0;
      for (const v of perAccount.values()) {
        totalLikes += v.likes;
        totalQuality += v.sends + v.saves;
      }
      const fleetAvgRatio = totalQuality > 0 ? totalLikes / totalQuality : 0;

      const flagged: VanityAccount[] = [];
      for (const [id, v] of perAccount) {
        if (instagramAccountId && id !== instagramAccountId) continue;
        if (v.likes < MIN_LIKES_FOR_SAMPLE) continue;
        const quality = v.sends + v.saves;
        const ratio = quality > 0 ? v.likes / quality : v.likes;
        const flagFloor = Math.max(
          MIN_RATIO_TO_FLAG,
          fleetAvgRatio * FLEET_MULTIPLE_TO_FLAG,
        );
        if (ratio < flagFloor) continue;
        flagged.push({
          accountId: id,
          handle: `@${handleById.get(id) ?? 'account'}`,
          platform: 'instagram',
          likes: v.likes,
          sends: v.sends,
          saves: v.saves,
          ratio,
        });
      }

      flagged.sort((a, b) => b.ratio - a.ratio);

      return {
        accounts: flagged.slice(0, 5),
        fleetAvgRatio: Math.round(fleetAvgRatio),
        hasRealData: true,
      };
    })(), 'vanity quality gap'),
  });

  return {
    ...(data ?? EMPTY),
    loading: !!userKey && isPending,
  };
}
