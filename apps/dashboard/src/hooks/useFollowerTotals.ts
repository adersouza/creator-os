import { useQuery } from "@tanstack/react-query";
import { supabase } from "@/services/supabase";
import { useAuthUser } from "@/hooks/useAuthUser";
import { queryClient } from "@/lib/queryClient";

export type FollowerTotalsPlatform = "all" | "threads" | "instagram";

interface FollowerTotals {
	total: number;
	accounts: number;
	isLoading: boolean;
	hasError: boolean;
}

const EMPTY = { total: 0, accounts: 0 };

type FollowerTotalsRaw = {
	threads: Array<{ id: string; followers_count: number | null }>;
	instagram: Array<{ id: string; follower_count: number | null }>;
};

export function useFollowerTotals(
	platform: FollowerTotalsPlatform = "all",
	accountIds?: string[] | null,
): FollowerTotals {
	const authUser = useAuthUser();
	const userKey = authUser?.id ?? null;
	const scopedIds = accountIds?.filter(Boolean) ?? [];
	const scopedKey = Array.isArray(accountIds)
		? scopedIds.slice().sort().join(",")
		: null;

	const { data, isPending, isError } = useQuery({
		queryKey: ["followerTotals", userKey, platform, scopedKey],
		enabled: !!userKey,
		staleTime: 5 * 60 * 1000,
		refetchOnWindowFocus: false,
		queryFn: async () => {
			if (!userKey) return EMPTY;
			if (Array.isArray(accountIds) && scopedIds.length === 0) return EMPTY;

			const raw = await queryClient.fetchQuery<FollowerTotalsRaw>({
				queryKey: ["followerTotalsRaw", userKey],
				staleTime: 5 * 60_000,
				gcTime: 15 * 60_000,
				queryFn: async () => {
					const [threadsRes, igRes] = await Promise.all([
						supabase
							.from("accounts")
							.select("id, followers_count")
							.eq("user_id", userKey)
							.eq("is_active", true)
							.eq("is_retired", false),
						supabase
							.from("instagram_accounts")
							.select("id, follower_count")
							.eq("user_id", userKey)
							.eq("is_active", true),
					]);

					if (threadsRes.error) throw threadsRes.error;
					if (igRes.error) throw igRes.error;

					return {
						threads: (threadsRes.data ?? []) as Array<{
							id: string;
							followers_count: number | null;
						}>,
						instagram: (igRes.data ?? []) as Array<{
							id: string;
							follower_count: number | null;
						}>,
					};
				},
			});

			const scopedSet = scopedIds.length > 0 ? new Set(scopedIds) : null;
			const threadRows =
				platform === "instagram"
					? []
					: scopedSet
						? raw.threads.filter((row) => scopedSet.has(row.id))
						: raw.threads;
			const igRows =
				platform === "threads"
					? []
					: scopedSet
						? raw.instagram.filter((row) => scopedSet.has(row.id))
						: raw.instagram;
			return {
				accounts: threadRows.length + igRows.length,
				total:
					threadRows.reduce((sum, row) => sum + (row.followers_count ?? 0), 0) +
					igRows.reduce((sum, row) => sum + (row.follower_count ?? 0), 0),
			};
		},
	});

	return {
		...(data ?? EMPTY),
		isLoading: !!userKey && isPending,
		hasError: !!userKey && isError,
	};
}
