import { useQuery } from "@tanstack/react-query";
import { useAuthUser } from "@/hooks/useAuthUser";
import { supabase } from "@/services/supabase";

interface ThreadsPostTotalsRow {
	views_count: number | null;
	replies_count: number | null;
	likes_count: number | null;
	reposts_count: number | null;
	quotes_count: number | null;
}

export interface ThreadsPostTotals {
	posts: number;
	views: number;
	replies: number;
	likes: number;
	reposts: number;
	quotes: number;
}

export const EMPTY_THREAD_TOTALS: ThreadsPostTotals = {
	posts: 0,
	views: 0,
	replies: 0,
	likes: 0,
	reposts: 0,
	quotes: 0,
};

/**
 * Exact Threads totals from published posts. Used as the dashboard fallback
 * when the fleet metrics RPC has not emitted Threads aggregate buckets yet.
 */
export function useThreadsPostTotals(
	days: number = 30,
	accountIds?: string[] | null,
) {
	const authUser = useAuthUser();
	const userKey = authUser?.id ?? null;
	const scopedIds = accountIds?.filter(Boolean) ?? [];
	const scopedKey = Array.isArray(accountIds)
		? scopedIds.slice().sort().join(",")
		: null;

	return useQuery<ThreadsPostTotals>({
		queryKey: ["threadsPostTotals", userKey, days, scopedKey],
		enabled: !!userKey,
		staleTime: 5 * 60 * 1000,
		refetchOnWindowFocus: false,
		queryFn: async () => {
			if (!userKey) return EMPTY_THREAD_TOTALS;
			if (Array.isArray(accountIds) && scopedIds.length === 0)
				return EMPTY_THREAD_TOTALS;
			const since = new Date();
			since.setDate(since.getDate() - days);
			since.setHours(0, 0, 0, 0);

			let query = supabase
				.from("posts")
				.select(
					"views_count, replies_count, likes_count, reposts_count, quotes_count",
				)
				.eq("user_id", userKey)
				.eq("platform", "threads")
				.eq("status", "published")
				.gte("published_at", since.toISOString());

			if (scopedIds.length > 0) query = query.in("account_id", scopedIds);

			const { data, error } = await query.limit(5000);

			if (error) throw error;

			return ((data ?? []) as ThreadsPostTotalsRow[]).reduce<ThreadsPostTotals>(
				(acc, row) => ({
					posts: acc.posts + 1,
					views: acc.views + (row.views_count ?? 0),
					replies: acc.replies + (row.replies_count ?? 0),
					likes: acc.likes + (row.likes_count ?? 0),
					reposts: acc.reposts + (row.reposts_count ?? 0),
					quotes: acc.quotes + (row.quotes_count ?? 0),
				}),
				EMPTY_THREAD_TOTALS,
			);
		},
	});
}
